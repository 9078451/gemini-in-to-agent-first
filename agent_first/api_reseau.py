"""L'API réseau d'Agent First : d'autres programmes (sur ce PC ou sur le réseau)
discutent avec Gemini au format OpenAI, lui font créer des images, des vidéos et de la
musique, ou lancent et suivent des tâches Cowork.

Elle écoute sur un port à part (8766, toutes les interfaces) ; chaque route `/v1`
exige la clé (`Authorization: Bearer …`), sauf un lien de média signé. L'app, elle,
reste sur 127.0.0.1:8765. La documentation interactive est sur `/docs`.
"""
import base64
import email.parser
import email.policy
import json
import logging
import os
import queue
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import TimeoutError as DelaiFutur
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as ExceptionHttp

from agent_first.cache_modes import CacheModes
from agent_first.cle_api import GardeCle
from agent_first.cowork_service import ServiceCowork, TacheEnCours
from agent_first.creation import TYPE_MEDIA, VARIANTE, format_depuis_taille, outil_depuis, requete_creation
from agent_first.envoi import Repartiteur
from agent_first.file_attente import FileAttente
from agent_first.fournisseurs import Fournisseur
from agent_first.historique import ConversationInconnue, Historique
from agent_first.mediatheque import Mediatheque
from agent_first.openai_compat import (
    completion,
    empreinte,
    mettre_a_plat,
    morceau,
    nettoyer_reponse,
    niveau_depuis_effort,
    pieces_du_message,
    resoudre_modele,
    resoudre_modele_site,
    suite_du_texte,
    texte_message,
    vers_api,
)
from agent_first.pieces_jointes import MAX_PIECES, PieceIllisible, depuis_base64, depuis_url
from agent_first.reglages_app import ReglagesApp
from agent_first.reponses import garder_reponse
from agent_first.serveur import reponse_media
from pilote.erreurs import ChoixBloque, ErreurPilote, LimiteAtteinte, ModeleIntrouvable, NiveauIntrouvable
from pilote.modeles import Media
from pilote.sites import GEMINI

journal = logging.getLogger(__name__)

CONVERSATIONS_MEMORISEES = 500
CREATIONS_MEMORISEES = 200
TYPES_ERREUR = {
    400: "invalid_request_error", 401: "authentication_error", 404: "not_found_error", 409: "conflict_error",
    429: "rate_limit_error", 500: "server_error", 502: "upstream_error", 504: "timeout_error",
}
MESSAGES_CLE = {401: "Missing or invalid API key (Authorization: Bearer <key>).",
                429: "Too many invalid keys from this address: try again in a minute."}
MODELE_PAR_DEFAUT = "agent-first"  # = le modèle déjà choisi dans Gemini
PING = 10.0  # s : un commentaire SSE pendant que Gemini réfléchit, pour que le client n'abandonne pas
MAX_OCTETS_INLINE = 25 * 1024 * 1024  # au-delà, un média n'est donné que par son lien
NOMS_TYPES = {"image": "image", "video": "video", "musique": "music"}


class DemandeChat(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    messages: list[dict]
    stream: bool = False
    reasoning_effort: str | None = None
    modalities: list[str] | None = None  # OpenRouter : ["image", "text"] demande une image
    media: str | None = None  # extension d'Agent First : "image", "video" ou "music"
    provider: str | None = None  # extension : "gemini", "chatgpt", "claude"… (sinon d'après `model`)
    redundancy: bool | None = None  # extension : passer à un autre assistant s'il est saturé (sinon le réglage de l'app)


class DemandeImage(BaseModel):
    """`POST /v1/images/generations`, au format OpenAI."""
    model_config = ConfigDict(extra="allow")
    prompt: str = Field(min_length=1)
    model: str | None = None
    n: int = Field(1, ge=1, le=4)
    size: str | None = None
    response_format: Literal["url", "b64_json"] = "url"
    reasoning_effort: str | None = None
    provider: str | None = None
    redundancy: bool | None = None


class DemandeMedia(BaseModel):
    """`POST /v1/media/generations` : une image, une vidéo ou de la musique."""
    model_config = ConfigDict(extra="allow")
    type: str = Field(description='"image", "video" ou "music"')
    prompt: str = Field(min_length=1)
    model: str | None = None
    n: int = Field(1, ge=1, le=4)
    size: str | None = Field(None, description='"1024x1024", "1792x1024" (paysage), "1024x1792" (portrait)')
    response_format: Literal["url", "b64_json"] = "url"
    reasoning_effort: str | None = None
    wait: bool = Field(True, description="false : répond tout de suite (202), suivre avec GET /v1/media/generations/{id}")
    images: list[str] = Field(default_factory=list, max_length=MAX_PIECES,
                              description="images ou fichiers de départ (adresses data: ou http(s)) : retouche, animation…")
    provider: str | None = Field(None, description='"gemini", "chatgpt"… (sinon d\'après `model`)')
    redundancy: bool | None = Field(None, description="passer à un autre assistant s'il est saturé (sinon le réglage de l'app)")


class NouvelleTache(BaseModel):
    folder: str
    request: str
    model: str | None = None
    reasoning_effort: str | None = None
    provider: str | None = None


class MessageTache(BaseModel):
    text: str


class DecisionTache(BaseModel):
    step: int
    approve: bool
    always: bool = False


@dataclass
class _Creation:
    """Une création de média lancée par l'API (suivie par GET /v1/media/generations/{id})."""
    id: str
    outil: str
    prompt: str
    cree: int = field(default_factory=lambda: int(time.time()))
    statut: str = "in_progress"  # puis « completed » ou « failed »
    texte: str = ""
    medias: list[dict] = field(default_factory=list)
    erreur: tuple[int, str] | None = None
    fini: threading.Event = field(default_factory=threading.Event)
    fournisseur: str = "gemini"  # celui qui a répondu en dernier (la redondance peut en changer)


# Le début d'un nom de modèle désigne l'assistant (« gpt-5 » → ChatGPT, « claude-opus » → Claude).
PREFIXES_FOURNISSEURS = (
    (("gpt", "chatgpt", "openai", "o1", "o3", "o4", "dall-e", "dalle", "sora"), "chatgpt"),
    (("claude", "anthropic"), "claude"),
    (("mistral", "le-chat", "lechat", "magistral", "codestral", "pixtral"), "mistral"),
    (("deepseek",), "deepseek"),
    (("grok", "xai"), "grok"),
    (("gemini", "google", "imagen", "veo", "lyria"), "gemini"),
)


def fournisseur_du_modele(modele: str | None, actifs: list[str]) -> str | None:
    """L'assistant qu'un nom de modèle désigne (« chatgpt/Thinking », « gpt-5 », « claude-sonnet-4-5 »),
    s'il est actif ; None sinon (le modèle est alors cherché chez le premier assistant)."""
    if not modele:
        return None
    nom = modele.strip().lower()
    tete = nom.split("/", 1)[0]
    if tete in actifs:  # « chatgpt/Thinking », « claude », « gemini/… »
        return tete
    for prefixes, fournisseur in PREFIXES_FOURNISSEURS:
        if any(nom == p or nom.startswith(tuple(p + c for c in "-._ /")) for p in prefixes):
            return fournisseur if fournisseur in actifs else None
    return None


def creer_api_reseau(
    file_chat: FileAttente,
    historique: Historique,
    cowork: ServiceCowork,
    garde: GardeCle,
    modes: CacheModes,
    delai: float,
    niveau_cowork: str | None = None,
    mediatheque: Mediatheque | None = None,
    delais_media: dict[str, float] | None = None,
    attente_file: float = 110.0,
    repartiteur: Repartiteur | None = None,
) -> FastAPI:
    """`file_chat` : la file de l'onglet du Chat de Gemini ; les tâches Cowork passent par celle de
    `cowork`. `delais_media` : limite de la réponse par outil de création (`attente_file` s'y
    ajoute). `repartiteur` : les assistants (Gemini, ChatGPT, Claude…) et la redondance ;
    par défaut, Gemini seul."""
    app = FastAPI(
        title="Agent First — API réseau",
        description="Gemini, ChatGPT, Claude… au format OpenAI (`/v1/chat/completions`, `/v1/images/generations`), "
        "images, vidéos et musique (`/v1/media/generations`), tâches Cowork (`/v1/cowork`). Le modèle choisit "
        "l'assistant (`gpt-…` → ChatGPT, `claude-…` → Claude, `chatgpt/Thinking`…). Chaque appel exige "
        "`Authorization: Bearer <clé>` (clé dans Paramètres de l'app).",
        version="5",
    )
    # La clé (un en-tête, jamais un cookie) protège chaque appel : une page web d'un autre
    # appareil peut appeler l'API, à condition de la connaître.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    delais_media = delais_media or {}
    if repartiteur is None:
        repartiteur = Repartiteur({"gemini": Fournisseur(GEMINI, file_chat, file_chat, modes)}, historique,
                                  ReglagesApp(None, ["gemini"]), delai, delais_media,
                                  attente_file)
    fournisseurs = repartiteur.fournisseurs
    memoire: OrderedDict[str, str] = OrderedDict()  # empreinte → conversation
    creations: OrderedDict[str, _Creation] = OrderedDict()
    verrou = threading.Lock()

    # Celle de Starlette (parente de celle de FastAPI) : corps illisible, route inconnue… aussi au format OpenAI.
    @app.exception_handler(ExceptionHttp)
    def erreur_http(_requete, exc: ExceptionHttp):
        return _erreur(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, exc: RequestValidationError):
        premiere = exc.errors()[0]
        champ = ".".join(str(c) for c in premiere.get("loc", ())[1:])
        return _erreur(400, f"Invalid request: {premiere.get('msg', 'bad body')}" + (f" ({champ})" if champ else ""))

    def authentifier(requete: Request) -> None:
        adresse = requete.client.host if requete.client else "?"
        code = garde.verifier(adresse, requete.headers.get("authorization"))
        if code is not None:
            raise HTTPException(code, MESSAGES_CLE[code])

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(authentifier)])

    @app.get("/health", include_in_schema=False)
    def sante():
        return {"ok": True}

    # ---- choisir l'assistant et le modèle ------------------------------

    def choisir(modele: str | None, fournisseur: str | None = None, outil: str | None = None) -> tuple[str, str | None]:
        """L'assistant et son modèle, d'après `provider` ou le nom du modèle (« gpt-5 » → ChatGPT,
        « chatgpt/Thinking », « claude-sonnet » → Claude…). Un nom inconnu garde Gemini et son
        modèle courant ; un assistant qui ne sait pas créer `outil` est refusé."""
        if fournisseur is not None and fournisseur not in fournisseurs:
            raise HTTPException(400, f"Unknown or disabled provider: {fournisseur} (available: {', '.join(fournisseurs)})")
        nom = fournisseur or fournisseur_du_modele(modele, list(fournisseurs)) or next(iter(fournisseurs))
        demande = modele.split("/", 1)[1] if modele and "/" in modele and modele.split("/", 1)[0].lower() in fournisseurs else modele
        if demande is not None and demande.strip().lower() in (nom, MODELE_PAR_DEFAUT, "default", "auto-provider"):
            demande = None
        resolu = None
        if demande:
            noms = [o.nom for o in fournisseurs[nom].modes.lire().modeles]
            if nom == "gemini":
                resolu = resoudre_modele(demande, noms)
            else:
                ignores = next((p for p, f in PREFIXES_FOURNISSEURS if f == nom), ()) + (nom,)
                resolu = resoudre_modele_site(demande, noms, ignores)
            if resolu is None:
                journal.info("Modèle « %s » inconnu de %s : son modèle courant sert", demande, fournisseurs[nom].libelle)
        if outil and outil not in fournisseurs[nom].outils:
            capables = [f.libelle for f in fournisseurs.values() if outil in f.outils]
            raise HTTPException(400, f"{fournisseurs[nom].libelle} cannot create {NOMS_TYPES[outil]}; use: {', '.join(capables)}")
        return nom, resolu

    def nom_du_modele(fournisseur: str, modele: str | None) -> str:
        """Le nom rendu au client : celui de Gemini tel quel, « chatgpt/Thinking » pour les autres."""
        if fournisseur == "gemini":
            return modele or MODELE_PAR_DEFAUT
        return f"{fournisseur}/{modele}" if modele else fournisseur

    def traduire(e: BaseException, limite: float) -> tuple[int, str]:
        """Une erreur d'un assistant ou de la file → (code HTTP, message)."""
        if isinstance(e, DelaiFutur):
            return 504, f"No answer after {limite:.0f} s (Agent First may be busy)."
        if isinstance(e, (ModeleIntrouvable, NiveauIntrouvable, ChoixBloque)):
            for f in fournisseurs.values():
                f.modes.oublier()  # la liste a changé : relue à la prochaine demande
            return 400, str(e)
        if isinstance(e, LimiteAtteinte):
            return 429, str(e)
        if isinstance(e, ErreurPilote):
            return 502, str(e)
        journal.error("Erreur inattendue pendant un appel de l'API réseau", exc_info=e)
        return 500, f"Unexpected error: {e}"

    def lien(requete: Request, decrit: dict) -> str:
        base = str(requete.base_url).rstrip("/")
        return f"{base}/v1/media/{decrit['id']}?sig={garde.signer(decrit['id'])}"

    def decrire(requete: Request, decrit: dict, en_ligne: bool = False) -> dict:
        """Un média pour l'API : lien signé (s'ouvre sans clé), et son contenu si demandé."""
        sortie = {
            "id": decrit["id"], "type": decrit["type"], "mime_type": decrit["mime"],
            "bytes": decrit["octets"], "url": lien(requete, decrit),
        }
        if decrit.get("description"):
            sortie["description"] = decrit["description"]
        if en_ligne:
            contenu = _lire(decrit)
            if contenu is not None:
                sortie["b64_json"] = base64.b64encode(contenu).decode("ascii")
        return sortie

    def _lire(decrit: dict) -> bytes | None:
        chemin = mediatheque.chemin(decrit["id"]) if mediatheque else None
        if chemin is None or decrit["octets"] > MAX_OCTETS_INLINE:
            return None
        return chemin.read_bytes()

    def _noter(conversation_id: str, role: str, texte: str, **details) -> None:
        try:
            historique.ajouter_message(conversation_id, role, texte, **details)
        except ConversationInconnue:
            pass

    def _noter_relais(conversation_id: str, ev: dict) -> None:
        _noter(conversation_id, "relais", f"{ev['de']} → {ev['vers']}", details=json.dumps(
            {k: ev[k] for k in ("type", "de", "vers", "fournisseur", "raison")}, ensure_ascii=False))

    def lire_pieces(adresses: list[tuple[str, str | None]]) -> list[Media]:
        if len(adresses) > MAX_PIECES:
            raise HTTPException(400, f"Too many attachments (at most {MAX_PIECES}).")
        try:
            return [depuis_url(url, nom) for url, nom in adresses]
        except PieceIllisible as e:
            raise HTTPException(400, str(e))

    def garder_pieces(conversation_id: str, pieces: list[Media]) -> list[dict]:
        return mediatheque.enregistrer(conversation_id, pieces) if mediatheque is not None and pieces else []

    # ---- format OpenAI -------------------------------------------------

    @v1.get("/models")
    def modeles():
        donnees = []
        for nom, f in fournisseurs.items():
            for o in f.modes.lire().modeles:  # Gemini : ses noms tels quels ; les autres : « chatgpt/Thinking »
                donnees.append({"id": o.nom if nom == "gemini" else f"{nom}/{o.nom}", "object": "model", "created": 0,
                                "owned_by": nom, "description": o.description})
            if nom != "gemini":
                donnees.append({"id": nom, "object": "model", "created": 0, "owned_by": nom,
                                "description": f"Le modèle déjà choisi dans {f.libelle}"})
        donnees.append({"id": MODELE_PAR_DEFAUT, "object": "model", "created": 0, "owned_by": "agent-first",
                        "description": "Le modèle déjà choisi dans Gemini"})
        return {"object": "list", "data": donnees}

    @v1.get("/models/{nom:path}")
    def modele(nom: str):
        for o in modeles()["data"]:
            if o["id"] == nom:
                return o
        raise HTTPException(404, f"Unknown model: {nom}")

    @v1.post("/chat/completions")
    def chat(demande: DemandeChat, requete: Request):
        if not any(m.get("role") == "user" for m in demande.messages):
            raise HTTPException(400, "messages must contain at least one user message")
        outil = outil_depuis(demande.media) or ("image" if "image" in (demande.modalities or []) else None)
        fournisseur, modele = choisir(demande.model, demande.provider, outil)
        niveau = niveau_depuis_effort(demande.reasoning_effort) if fournisseur == "gemini" else None
        dernier = texte_message(demande.messages[-1].get("content"))
        cle = f"{fournisseur}:{modele}"
        with verrou:
            connue = memoire.get(empreinte(cle, demande.messages[:-1])) if len(demande.messages) > 1 else None
        if connue:
            try:
                historique.conversation(connue)
            except ConversationInconnue:
                connue = None  # retirée de l'historique entre-temps
        # Les fichiers du dernier message ; dans une conversation neuve, ceux de tout l'historique.
        avec_pieces = [demande.messages[-1]] if connue else [m for m in demande.messages if m.get("role") == "user"]
        pieces = lire_pieces([p for m in avec_pieces for p in pieces_du_message(m.get("content"))])
        conversation_id = connue or historique.creer(modele, niveau, "chat", None, source="api", fournisseur=fournisseur).id
        _noter(conversation_id, "toi", dernier, modele=modele, niveau=niveau,
               details=json.dumps({"outil": outil}) if outil else None, medias=garder_pieces(conversation_id, pieces))

        def rediger(_nom: str, adresse: str | None) -> str:
            # Un assistant qui n'a pas vu la conversation (nouvelle, ou relais) reçoit tout l'historique.
            texte = dernier if adresse is not None else mettre_a_plat(demande.messages)
            return requete_creation(outil, texte, suite=adresse is not None, joints=bool(pieces)) if outil else texte

        def apres(resultat, nom):
            message, decrits = garder_reponse(historique, mediatheque, conversation_id, resultat, fournisseur=nom)
            return resultat, (message.texte if message else nettoyer_reponse(resultat.reponse)), decrits

        limite = repartiteur.limite(outil)
        deroulement = repartiteur.deroulement(
            conversation_id, rediger, modele, niveau, outil, tuple(pieces), demande.redundancy, apres=apres,
            direct=demande.stream,
        )

        def repondre(fini: dict) -> tuple[str, str, dict]:
            resultat, contenu, decrits = fini["retour"]
            medias = [decrire(requete, d) for d in decrits]
            if medias:  # les clients qui n'affichent que le texte voient quand même les médias
                contenu = "\n\n".join(filter(None, [contenu, *(_markdown(m) for m in medias)]))
            suite = demande.messages + [{"role": "assistant", "content": contenu}]
            with verrou:
                memoire[empreinte(cle, suite)] = conversation_id
                while len(memoire) > CONVERSATIONS_MEMORISEES:
                    memoire.popitem(last=False)
            extras = {}
            if medias:
                extras["media"] = medias
                images = [_data_url(d, _lire(d)) for d in decrits if d["type"] == "image"]
                if any(images):  # format d'OpenRouter pour les images créées
                    extras["images"] = [{"type": "image_url", "image_url": {"url": u}} for u in images if u]
            return contenu, nom_du_modele(fini["fournisseur"], resultat.modele or modele), extras

        if demande.stream:
            def flux() -> Iterator[str]:
                """Le texte part au fil de l'écriture de l'assistant ; les médias, à la fin."""
                base = {"id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion.chunk",
                        "created": int(time.time()), "model": demande.model or MODELE_PAR_DEFAUT}
                yield morceau(base, {"role": "assistant", "content": ""})
                envoye, deja, calme_depuis = "", "", time.monotonic()
                file_evenements: queue.Queue = queue.Queue()

                def produire() -> None:
                    try:
                        for ev in deroulement:
                            file_evenements.put(ev)
                    except BaseException as e:  # remis au fil du flux, qui en fait une erreur OpenAI
                        file_evenements.put({"type": "exception", "erreur": e})
                    finally:
                        file_evenements.put({"type": "_fin"})

                threading.Thread(target=produire, name="flux-chat", daemon=True).start()
                fini = None
                while True:
                    try:
                        ev = file_evenements.get(timeout=0.25)
                    except queue.Empty:
                        if time.monotonic() - calme_depuis >= PING:
                            calme_depuis = time.monotonic()
                            yield ": ping\n\n"
                        continue
                    if ev["type"] == "texte":
                        base["provider"] = ev["fournisseur"]  # comme OpenRouter : l'assistant qui écrit
                        ajout = suite_du_texte(envoye, ev["texte"])
                        if ajout:
                            envoye += ajout
                            calme_depuis = time.monotonic()
                            yield morceau(base, {"content": ajout})
                    elif ev["type"] == "relais":
                        _noter_relais(conversation_id, ev)
                        base["provider"] = ev["fournisseur"]
                        # Le client a déjà reçu un début : il est clos, l'autre assistant repart de zéro.
                        separation = f"\n\n— {ev['vers']} prend le relais —\n\n" if envoye else ""
                        deja, envoye = deja + envoye + separation, ""
                        if separation:
                            yield morceau(base, {"content": separation})
                    elif ev["type"] == "fin":
                        fini = ev
                    elif ev["type"] == "exception":
                        code, message = traduire(ev["erreur"], limite)
                        _noter(conversation_id, "erreur", message)
                        yield f"data: {json.dumps(_corps_erreur(code, message), ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    elif ev["type"] == "_fin":
                        break
                contenu, nom, extras = repondre(fini)
                reste = suite_du_texte(envoye, contenu)
                if reste is None:  # rare : l'assistant a réécrit un passage déjà envoyé
                    journal.info("Flux : la fin de la réponse ne prolonge pas le texte déjà envoyé")
                    reste = contenu[len(os.path.commonprefix([envoye, contenu])):]
                base["model"], base["provider"] = nom, fini["fournisseur"]
                if reste or extras:
                    yield morceau(base, {"content": reste, **extras})
                yield morceau(base, {}, "stop")
                yield "data: [DONE]\n\n"

            return StreamingResponse(flux(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

        fini = None
        try:
            for ev in deroulement:
                if ev["type"] == "relais":
                    _noter_relais(conversation_id, ev)
                elif ev["type"] == "fin":
                    fini = ev
        except Exception as e:
            code, message = traduire(e, limite)
            _noter(conversation_id, "erreur", message)
            raise HTTPException(code, message)
        contenu, nom, extras = repondre(fini)
        return {**completion(contenu, nom, dernier, extras), "provider": fini["fournisseur"]}

    # ---- images, vidéos, musique ---------------------------------------

    def creer(outil: str, prompt: str, nombre: int, format: str | None, fournisseur: str, modele: str | None,
              niveau: str | None, pieces: list[Media] | None = None, redondance: bool | None = None) -> _Creation:
        """Lance une création dans un fil à part ; `fini` est levé à la fin. `pieces` : les
        fichiers de départ (photo à retoucher…), joints au premier message."""
        pieces = pieces or []
        conversation = historique.creer(modele, niveau, "chat", None, source="api", fournisseur=fournisseur)
        creation = _Creation(conversation.id, outil, prompt, fournisseur=fournisseur)
        with verrou:
            creations[creation.id] = creation
            while len(creations) > CREATIONS_MEMORISEES:
                creations.popitem(last=False)
        _noter(creation.id, "toi", prompt, modele=modele, niveau=niveau, details=json.dumps({"outil": outil}),
               medias=garder_pieces(creation.id, pieces))

        def rediger(_nom: str, adresse: str | None) -> str:
            # Une variante dans la même conversation ; tout depuis le début chez un nouvel assistant.
            return VARIANTE[outil] if adresse is not None else requete_creation(outil, prompt, format, joints=bool(pieces))

        def derouler() -> None:
            limite = repartiteur.limite(outil)
            try:
                for essai in range(nombre):  # un média par message, en général
                    if essai and len(creation.medias) >= nombre:
                        break

                    def apres(resultat, nom):
                        return garder_reponse(historique, mediatheque, creation.id, resultat, fournisseur=nom)[1], resultat

                    fini = repartiteur.envoyer(
                        creation.id, rediger, modele=modele if not essai else None, niveau=niveau if not essai else None,
                        outil=outil, pieces=tuple(pieces) if not essai else (), redondance=redondance, apres=apres,
                    )
                    for ev in fini["relais"]:
                        _noter_relais(creation.id, ev)
                    creation.fournisseur = fini["fournisseur"]
                    decrits, resultat = fini["retour"]
                    creation.texte = "\n\n".join(filter(None, [creation.texte, nettoyer_reponse(resultat.reponse)]))
                    creation.medias += [d for d in decrits if d["type"] == TYPE_MEDIA[outil]]
                    if not decrits:
                        break  # refus ou outil indisponible : inutile d'insister
                if creation.medias:
                    creation.medias = creation.medias[:nombre]
                    creation.statut = "completed"
                else:
                    creation.statut = "failed"
                    libelle = fournisseurs[creation.fournisseur].libelle
                    detail = f" {libelle}'s answer: {creation.texte}" if creation.texte else ""
                    creation.erreur = (502, f"{libelle} did not create any {NOMS_TYPES[outil]}.{detail}")
            except Exception as e:
                creation.statut, creation.erreur = "failed", traduire(e, limite)
                _noter(creation.id, "erreur", creation.erreur[1])
            finally:
                creation.fini.set()

        threading.Thread(target=derouler, name=f"creation-{creation.id[:8]}", daemon=True).start()
        return creation

    def limite_creation(outil: str, nombre: int) -> float:
        return (delais_media.get(outil, delai) + attente_file) * nombre

    def etat_creation(requete: Request, creation: _Creation, en_ligne: bool) -> dict:
        etat = {
            "id": creation.id, "object": "media.generation", "type": NOMS_TYPES[creation.outil],
            "status": creation.statut, "created": creation.cree, "prompt": creation.prompt,
            "text": creation.texte, "provider": creation.fournisseur,
            "data": [decrire(requete, d, en_ligne) for d in creation.medias],
        }
        if creation.erreur:
            etat["error"] = {"message": creation.erreur[1], "type": TYPES_ERREUR.get(creation.erreur[0], "error"),
                             "code": creation.erreur[0]}
        return etat

    @v1.post("/images/generations")
    def images(demande: DemandeImage, requete: Request):
        return creer_images(requete, demande.prompt, demande.n, demande.size, demande.response_format,
                            demande.model, demande.reasoning_effort, provider=demande.provider,
                            redondance=demande.redundancy)

    @v1.post("/images/edits")
    async def images_retouchees(requete: Request):
        """Retoucher une ou plusieurs images (format OpenAI, multipart : `image` ou `image[]`,
        `prompt`, `n`, `size`, `response_format`) ; aussi en JSON (`images` : adresses). Gemini ne
        prend pas de masque : `mask` est ignoré, décris la zone à changer dans `prompt`."""
        champs, pieces = await _formulaire(requete)
        if not champs.get("prompt", "").strip():
            raise HTTPException(400, "prompt is required")
        if not pieces:
            raise HTTPException(400, "image is required")
        try:
            nombre = max(1, min(4, int(champs.get("n") or 1)))
        except ValueError:
            raise HTTPException(400, "n must be an integer")
        format_reponse = champs.get("response_format") or "url"
        redondance = champs.get("redundancy")
        return await run_in_threadpool(
            creer_images, requete, champs["prompt"], nombre, champs.get("size"), format_reponse,
            champs.get("model"), champs.get("reasoning_effort"), pieces, champs.get("provider") or None,
            None if redondance is None else redondance.strip().lower() in ("1", "true", "yes", "on"),
        )

    def creer_images(requete: Request, prompt: str, nombre: int, taille: str | None, format_reponse: str,
                     modele: str | None, effort: str | None, pieces: list[Media] | None = None,
                     provider: str | None = None, redondance: bool | None = None) -> dict:
        fournisseur, modele = choisir(modele, provider, "image")
        creation = creer("image", prompt, nombre, format_depuis_taille(taille), fournisseur, modele,
                         niveau_depuis_effort(effort) if fournisseur == "gemini" else None, pieces, redondance)
        creation.fini.wait(limite_creation("image", nombre) + 5)
        if creation.statut != "completed":
            code, message = creation.erreur or (504, "Image creation is still running.")
            raise HTTPException(code, message)
        donnees = []
        for d in creation.medias:
            if format_reponse == "b64_json":
                contenu = _lire(d)
                donnees.append({"b64_json": base64.b64encode(contenu).decode("ascii")} if contenu else {"url": lien(requete, d)})
            else:
                donnees.append({"url": lien(requete, d)})
            if creation.texte:
                donnees[-1]["revised_prompt"] = creation.texte
        return {"created": creation.cree, "data": donnees}

    async def _formulaire(requete: Request) -> tuple[dict[str, str], list[Media]]:
        """Les champs et fichiers d'un envoi multipart (sans dépendance de plus), ou d'un JSON."""
        corps = await requete.body()
        type_contenu = requete.headers.get("content-type", "")
        if type_contenu.startswith("application/json"):
            try:
                donnees = json.loads(corps or b"{}")
            except ValueError:
                raise HTTPException(400, "Invalid JSON body")
            adresses = donnees.get("images") or ([donnees["image"]] if isinstance(donnees.get("image"), str) else [])
            champs = {k: str(v) for k, v in donnees.items() if k not in ("images", "image") and v is not None}
            return champs, await run_in_threadpool(lire_pieces, [(a, None) for a in adresses if isinstance(a, str)])
        if not type_contenu.startswith("multipart/form-data"):
            raise HTTPException(400, "Expected multipart/form-data or application/json")
        message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            f"Content-Type: {type_contenu}\r\n\r\n".encode("latin-1") + corps)
        champs, pieces = {}, []
        for partie in message.iter_parts():
            nom = partie.get_param("name", header="content-disposition") or ""
            contenu = partie.get_payload(decode=True) or b""
            if partie.get_filename() is not None:
                if nom.startswith("image"):  # « image », « image[] » ; « mask » est ignoré
                    try:
                        pieces.append(depuis_base64(partie.get_filename() or "image.png", partie.get_content_type(),
                                                    base64.b64encode(contenu).decode("ascii")))
                    except PieceIllisible as e:
                        raise HTTPException(400, str(e))
            else:
                champs[nom] = contenu.decode("utf-8", "replace")
        if len(pieces) > MAX_PIECES:
            raise HTTPException(400, f"Too many images (at most {MAX_PIECES}).")
        return champs, pieces

    @v1.post("/media/generations")
    def medias(demande: DemandeMedia, requete: Request):
        outil = outil_depuis(demande.type)
        if outil is None:
            raise HTTPException(400, 'type must be "image", "video" or "music"')
        fournisseur, modele = choisir(demande.model, demande.provider, outil)
        creation = creer(outil, demande.prompt, demande.n, format_depuis_taille(demande.size), fournisseur, modele,
                         niveau_depuis_effort(demande.reasoning_effort) if fournisseur == "gemini" else None,
                         lire_pieces([(a, None) for a in demande.images]), demande.redundancy)
        en_ligne = demande.response_format == "b64_json"
        if not demande.wait:
            return JSONResponse(status_code=202, content=etat_creation(requete, creation, False))
        creation.fini.wait(limite_creation(outil, demande.n) + 5)
        etat = etat_creation(requete, creation, en_ligne)
        if creation.statut == "failed":
            return JSONResponse(status_code=creation.erreur[0], content={**etat, **_corps_erreur(*creation.erreur)})
        return JSONResponse(status_code=200 if creation.statut == "completed" else 202, content=etat)

    @v1.get("/media/generations/{identifiant}")
    def suivre_creation(identifiant: str, requete: Request, response_format: Literal["url", "b64_json"] = "url"):
        with verrou:
            creation = creations.get(identifiant)
        if creation is None:
            creation = _creation_depuis_historique(identifiant)
        return etat_creation(requete, creation, response_format == "b64_json")

    def _creation_depuis_historique(identifiant: str) -> _Creation:
        """Après un redémarrage d'Agent First : l'état se lit dans l'historique."""
        try:
            messages = historique.messages(identifiant)
        except ConversationInconnue:
            raise HTTPException(404, f"Unknown generation: {identifiant}")
        demande = next((m for m in messages if m.role == "toi" and m.details), None)
        outil = json.loads(demande.details).get("outil") if demande else None
        if outil not in NOMS_TYPES:
            raise HTTPException(404, f"Unknown generation: {identifiant}")
        creation = _Creation(identifiant, outil, demande.texte, fournisseur=historique.conversation(identifiant).fournisseur)
        reponses = [m for m in messages if m.role == "gemini"]
        creation.texte = "\n\n".join(m.texte for m in reponses if m.texte)
        creation.medias = [d for m in reponses for d in m.medias if d["type"] == TYPE_MEDIA[outil]]
        erreurs = [m.texte for m in messages if m.role == "erreur"]
        if creation.medias:
            creation.statut = "completed"
        else:
            creation.statut = "failed"
            creation.erreur = (502, erreurs[-1] if erreurs else "Interrupted (Agent First was restarted).")
        creation.fini.set()
        return creation

    @v1.get("/conversations/{identifiant}")
    def conversation(identifiant: str, requete: Request):
        """Une conversation de l'historique et ses médias (pour les retrouver plus tard)."""
        try:
            lue = historique.conversation(identifiant)
            messages = historique.messages(identifiant)
        except ConversationInconnue:
            raise HTTPException(404, f"Unknown conversation: {identifiant}")
        roles = {"toi": "user", "gemini": "assistant", "erreur": "error", "cowork": "cowork", "relais": "relay"}
        return {
            "id": lue.id, "title": lue.titre, "mode": lue.mode, "model": lue.modele, "provider": lue.fournisseur,
            "created": lue.cree_le,
            "messages": [
                {"role": roles.get(m.role, m.role), "content": m.texte, "created": m.cree_le,
                 "media": [decrire(requete, d) for d in m.medias]}
                for m in messages if m.role != "cowork"
            ],
        }

    # ---- Cowork --------------------------------------------------------

    @v1.post("/cowork")
    def cowork_creer(demande: NouvelleTache):
        refus = _dossier_refuse(demande.folder)
        if refus:
            raise HTTPException(400, refus)
        # Sans niveau demandé : celui de l'app (Min.). Gemini garderait son réglage, souvent « Max. »,
        # qui abandonne une longue demande Cowork sans répondre (vu en essai réel).
        fournisseur, modele = choisir(demande.model, demande.provider)
        niveau = (niveau_depuis_effort(demande.reasoning_effort) or niveau_cowork) if fournisseur == "gemini" else None
        dossier = str(Path(demande.folder).resolve())
        conversation = historique.creer(modele, niveau, "cowork", dossier, source="api", fournisseur=fournisseur)
        return _lancer(conversation.id, demande.request)

    @v1.post("/cowork/{identifiant}/messages")
    def cowork_message(identifiant: str, demande: MessageTache):
        conversation = _tache_connue(identifiant)
        if conversation.mode != "cowork" or not conversation.dossier:
            raise HTTPException(400, "This conversation is not a Cowork task.")
        return _lancer(identifiant, demande.text)

    def _lancer(identifiant: str, texte: str) -> dict:
        if cowork.en_cours(identifiant):
            raise HTTPException(409, "A task is already running in this conversation: wait for it or stop it.")
        conversation = historique.conversation(identifiant)
        try:  # le service enregistre le message s'il accepte la tâche
            cowork.demarrer(identifiant, conversation.dossier, conversation.adresse, texte,
                            conversation.modele, conversation.niveau, fournisseur=conversation.fournisseur)
        except TacheEnCours:
            raise HTTPException(409, "A task is already running in this conversation: wait for it or stop it.")
        return {"id": identifiant, "status": cowork.etat(identifiant)["statut"]}

    @v1.get("/cowork/{identifiant}")
    def cowork_etat(identifiant: str):
        _tache_connue(identifiant)
        etat = cowork.etat(identifiant)
        return {"id": identifiant, **vers_api({k: etat[k] for k in ("statut", "plan", "resume", "question", "bilan", "evenements")})}

    @v1.get("/cowork/{identifiant}/events")
    def cowork_evenements(identifiant: str, since: int = 0):
        _tache_connue(identifiant)
        return StreamingResponse(_traduire(cowork.flux(identifiant, since)), media_type="text/event-stream")

    @v1.post("/cowork/{identifiant}/decision")
    def cowork_decision(identifiant: str, decision: DecisionTache):
        _tache_connue(identifiant)
        if not cowork.decider(identifiant, decision.step, "continuer" if decision.approve else "refuser", decision.always):
            raise HTTPException(409, f"No pending approval for step {decision.step}.")
        return {"ok": True}

    @v1.post("/cowork/{identifiant}/stop")
    def cowork_arreter(identifiant: str):
        _tache_connue(identifiant)
        cowork.arreter(identifiant)
        return {"ok": True}

    @v1.post("/cowork/{identifiant}/processes/{numero}/stop")
    def cowork_arreter_processus(identifiant: str, numero: str):
        _tache_connue(identifiant)
        resultat = cowork.arreter_processus(identifiant, numero)
        return {"ok": resultat.ok, "output": resultat.corps}

    def _tache_connue(identifiant: str):
        try:
            return historique.conversation(identifiant)
        except ConversationInconnue:
            raise HTTPException(404, f"Unknown conversation: {identifiant}")

    app.include_router(v1)

    # Après le routeur : /v1/media/generations/{id} passe avant cette route.
    @app.get("/v1/media/{conversation}/{fichier}", tags=["media"])
    def fichier_media(conversation: str, fichier: str, requete: Request, sig: str | None = None,
                      download: bool = False):
        """Le fichier d'un média. Avec `sig` (lien donné par l'API), sans clé ; sinon, la clé."""
        identifiant = f"{conversation}/{fichier}"
        if not garde.signature_valide(identifiant, sig):
            authentifier(requete)
        chemin = mediatheque.chemin(identifiant) if mediatheque else None
        if chemin is None:
            raise HTTPException(404, f"Unknown media: {identifiant}")
        return reponse_media(chemin, download)

    return app


def _corps_erreur(code: int, message: str) -> dict:
    return {"error": {"message": message, "type": TYPES_ERREUR.get(code, "error"), "code": code}}


def _erreur(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content=_corps_erreur(code, message))


def _markdown(media: dict) -> str:
    nom = {"image": "Image", "video": "Vidéo", "audio": "Audio"}.get(media["type"], "Média")
    return f"![{nom}]({media['url']})" if media["type"] == "image" else f"[{nom}]({media['url']})"


def _data_url(decrit: dict, contenu: bytes | None) -> str | None:
    return f"data:{decrit['mime']};base64,{base64.b64encode(contenu).decode('ascii')}" if contenu else None


def _traduire(flux: Iterator[str]) -> Iterator[str]:
    for ligne in flux:
        if ligne.startswith("data: "):
            ligne = f"data: {json.dumps(vers_api(json.loads(ligne[6:])), ensure_ascii=False)}\n\n"
        yield ligne


def _dossier_refuse(dossier: str) -> str | None:
    """Pourquoi ce dossier ne peut pas servir de dossier de travail, ou None s'il convient."""
    chemin = Path(dossier)
    if not chemin.is_absolute():
        return "folder must be an absolute path"
    if not chemin.is_dir():
        return f"folder not found: {dossier}"
    resolu = chemin.resolve()
    if resolu.parent == resolu:
        return "a drive root cannot be a working folder"
    for variable in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        base = os.environ.get(variable)
        if base and (resolu == Path(base).resolve() or resolu.is_relative_to(Path(base).resolve())):
            return "system folders cannot be working folders"
    return None
