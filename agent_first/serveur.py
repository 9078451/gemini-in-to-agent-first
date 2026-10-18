"""API HTTP locale d'Agent First (n'écoute que sur 127.0.0.1)."""
import io
import json
import logging
import re
import threading
import zipfile
from concurrent.futures import CancelledError
from concurrent.futures import TimeoutError as DelaiFutur
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterator, Literal
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from agent_first.cache_modes import CacheModes
from agent_first.cle_api import GardeCle
from agent_first.cowork_service import TacheEnCours
from agent_first.creation import requete_creation
from agent_first.diffuseur import Diffuseur
from agent_first.envoi import Repartiteur, Tentative, peut_basculer, transcription
from agent_first.file_attente import FileAttente, attendre
from agent_first.fournisseurs import Fournisseur
from agent_first.historique import ConversationInconnue, Historique
from agent_first.mediatheque import Mediatheque, mime_de
from agent_first.nettoyage import nettoyer_html
from agent_first.pieces_jointes import MAX_PIECES, PieceIllisible, depuis_base64
from agent_first.reglages_app import ReglagesApp
from agent_first.reponses import garder_reponse
from pilote.erreurs import ChoixBloque, ErreurPilote, LimiteAtteinte, ModeleIntrouvable, NiveauIntrouvable
from pilote.modeles import Modes, ResultatGemini
from pilote.sites import GEMINI, SITES

journal = logging.getLogger(__name__)

Periode = Literal["7j", "30j", "tout"]
Outil = Literal["image", "video", "musique"]
INCONNUE = "Conversation inconnue : démarre une nouvelle conversation."
EN_COURS = "Une tâche tourne déjà dans cette conversation : attends sa fin ou arrête-la."


class NouvelleConversation(BaseModel):
    modele: str | None = None
    niveau: str | None = None
    mode: str = "chat"
    dossier: str | None = None
    fournisseur: str = "gemini"  # « gemini », « chatgpt », « claude »…


class ChangementFournisseur(BaseModel):
    fournisseur: str
    modele: str | None = None


class NouveauxReglages(BaseModel):
    redondance: bool | None = None
    ordre: list[str] | None = None


class PieceJointe(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    mime: str = "application/octet-stream"
    donnees: str  # base64


class NouveauMessage(BaseModel):
    texte: str
    modele: str | None = None
    niveau: str | None = None
    outil: Outil | None = None  # créer une image, une vidéo, de la musique
    pieces: list[PieceJointe] = Field(default_factory=list, max_length=MAX_PIECES)  # fichiers joints
    redondance: bool | None = None  # None : le réglage de l'app

    @field_validator("texte")
    @classmethod
    def texte_non_vide(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("le message est vide")
        return valeur


class MessageCowork(BaseModel):
    texte: str

    @field_validator("texte")
    @classmethod
    def texte_non_vide(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("le message est vide")
        return valeur


class Decision(BaseModel):
    etape: int
    reponse: str
    toujours: bool = False


def erreur(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"erreur": message})


def ligne(evenement: dict) -> str:
    return json.dumps(evenement, ensure_ascii=False) + "\n"


def reponse_media(chemin: Path, telecharger: bool = False) -> FileResponse:
    """Un média de la médiathèque. Jamais exécuté comme une page (bac à sable) : il est
    servi depuis l'origine de l'app, qui connaît la clé de l'API."""
    return FileResponse(
        chemin, media_type=mime_de(chemin), filename=f"agent-first-{chemin.name}",
        content_disposition_type="attachment" if telecharger else "inline",
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; media-src 'self'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=31536000, immutable",  # un fichier ne change jamais
        },
    )


def creer_app(
    file_chat: FileAttente,
    historique: Historique,
    delai: float,
    chrome_lance: Callable[[], bool],
    modes_par_defaut: Modes,
    dossier_web: Path | None = None,
    cowork=None,
    choisir_dossier: Callable[[], str | None] | None = None,
    diffuseur: Diffuseur | None = None,
    cache_modes: CacheModes | None = None,
    garde_api: GardeCle | None = None,
    adresse_api: str | None = None,
    hotes_autorises: list[str] | None = None,
    mediatheque: Mediatheque | None = None,
    delais_media: dict[str, float] | None = None,
    attente_file: float = 110.0,
    repartiteur: Repartiteur | None = None,
    reglages: ReglagesApp | None = None,
) -> FastAPI:
    """`file_chat` : la file de l'onglet du Chat de Gemini (messages, état de Google, modèles) ;
    les tâches Cowork passent par celle du service `cowork`. `delais_media` : limite de la
    réponse par outil de création ; `attente_file` s'y ajoute (attente de son tour).
    `repartiteur` : les assistants (Gemini, ChatGPT…) et la redondance ; par défaut, Gemini seul."""
    app = FastAPI(title="Agent First")
    delais_media = delais_media or {}
    connus: dict[str, bool | None] = {}  # dernier état lu de la connexion à chaque site
    en_vol: dict[str, Tentative] = {}  # conversation → envoi du Chat en cours (pour l'arrêter)
    verrou_vol = threading.Lock()
    if hotes_autorises:
        # Une page web ne doit pas pouvoir joindre l'app par « reliure DNS » (et lire la clé de l'API).
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hotes_autorises)
    modes = cache_modes or CacheModes(file_chat, chrome_lance, modes_par_defaut)
    if repartiteur is None:
        reglages = reglages or ReglagesApp(None, ["gemini"])
        repartiteur = Repartiteur({"gemini": Fournisseur(GEMINI, file_chat, file_chat, modes)}, historique, reglages,
                                  delai, delais_media, attente_file)
    reglages = reglages or repartiteur._reglages
    fournisseurs = repartiteur.fournisseurs

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, _exc):
        return erreur(422, "Message vide ou demande invalide.")

    @app.get("/api/etat")
    def etat():
        lance = chrome_lance()
        for nom, f in fournisseurs.items():
            if not lance:
                connus[nom] = None
            elif f.file_chat.pilote_pret() or nom == "gemini":
                if not f.file_chat.occupee():
                    # Onglet occupé (une vidéo peut prendre des minutes) : le dernier état lu sert,
                    # sans mettre une vérification en file derrière la demande en cours.
                    try:
                        connus[nom] = attendre(f.file_chat.soumettre(lambda pilote: pilote.est_connecte()), 5)
                    except Exception:
                        connus[nom] = None  # injoignable : inconnu
            else:
                connus[nom] = None  # fenêtre pas encore ouverte : inconnu, sans l'ouvrir
        return {"agent_first": True, "chrome": lance, "google": connus.get("gemini") if lance else None,
                "fournisseurs": {nom: connus.get(nom) for nom in fournisseurs}}

    @app.get("/api/modeles")
    def modeles(fournisseur: str = "gemini"):
        f = fournisseurs.get(fournisseur)
        if f is None:
            return erreur(404, f"Assistant inconnu : {fournisseur}.")
        return asdict(f.modes.lire())

    @app.get("/api/fournisseurs")
    def lister_fournisseurs():
        """Les assistants proposés, leurs modèles et ce qu'ils savent créer."""
        return [f.decrire() for f in fournisseurs.values()]

    @app.get("/api/reglages")
    def lire_reglages():
        return reglages.lire()

    @app.post("/api/reglages")
    def ecrire_reglages(demande: NouveauxReglages):
        return reglages.ecrire(demande.redondance, demande.ordre)

    @app.get("/api/conversations")
    def conversations(recherche: str = "", periode: Periode = "tout"):
        return [asdict(c) for c in historique.lister(recherche, periode)]

    @app.post("/api/conversations")
    def nouvelle_conversation(demande: NouvelleConversation | None = None):
        choix = demande or NouvelleConversation()
        if choix.fournisseur not in fournisseurs:
            return erreur(422, f"Assistant inconnu ou désactivé : {choix.fournisseur} (FOURNISSEURS dans config.py).")
        return asdict(
            historique.creer(choix.modele, choix.niveau, choix.mode, choix.dossier, fournisseur=choix.fournisseur)
        )

    @app.post("/api/conversations/{identifiant}/fournisseur")
    def changer_fournisseur(identifiant: str, demande: ChangementFournisseur):
        """La conversation continue avec un autre assistant (il recevra la transcription)."""
        if demande.fournisseur not in fournisseurs:
            return erreur(422, f"Assistant inconnu ou désactivé : {demande.fournisseur}.")
        try:
            conversation = historique.conversation(identifiant)
            if conversation.fournisseur != demande.fournisseur:
                historique.basculer(identifiant, demande.fournisseur, demande.modele)
            return asdict(historique.conversation(identifiant))
        except ConversationInconnue:
            return erreur(404, INCONNUE)

    @app.post("/api/cowork/{identifiant}/messages")
    def cowork_message(identifiant: str, demande: MessageCowork):
        try:
            conv = historique.conversation(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        if conv.mode != "cowork" or not conv.dossier:
            return erreur(422, "Cette conversation n'est pas une tâche Cowork avec un dossier.")
        if cowork.en_cours(identifiant):
            return erreur(409, EN_COURS)
        try:  # le service enregistre le message s'il accepte la tâche
            cowork.demarrer(identifiant, conv.dossier, conv.adresse, demande.texte, conv.modele, conv.niveau,
                            fournisseur=conv.fournisseur)
        except TacheEnCours:
            return erreur(409, EN_COURS)
        return {"ok": True}

    @app.get("/api/cowork/{identifiant}/flux")
    def cowork_flux(identifiant: str, depuis: int = 0):
        return StreamingResponse(cowork.flux(identifiant, depuis), media_type="text/event-stream")

    @app.get("/api/cowork/{identifiant}/processus")
    def cowork_processus(identifiant: str):
        return {"processus": cowork.processus(identifiant)}

    @app.post("/api/cowork/{identifiant}/processus/{numero}/arreter")
    def cowork_arreter_processus(identifiant: str, numero: str):
        resultat = cowork.arreter_processus(identifiant, numero)
        return {"ok": resultat.ok, "corps": resultat.corps, "processus": cowork.processus(identifiant)}

    @app.get("/api/evenements")
    def evenements():
        if diffuseur is None:
            return erreur(404, "Pas de flux d'évènements.")
        return StreamingResponse(diffuseur.flux(cowork.etats_en_cours if cowork else None), media_type="text/event-stream")

    @app.post("/api/cowork/{identifiant}/decision")
    def cowork_decision(identifiant: str, decision: Decision):
        if not cowork.decider(identifiant, decision.etape, decision.reponse, decision.toujours):
            return erreur(409, "Aucune demande d'accord en attente pour cette étape.")
        return {"ok": True}

    @app.post("/api/cowork/{identifiant}/arreter")
    def cowork_arreter(identifiant: str):
        cowork.arreter(identifiant)
        return {"ok": True}

    @app.get("/api/api-reseau")
    def api_reseau():
        if garde_api is None:
            return {"active": False, "adresse": None, "cle": None}
        return {"active": True, "adresse": adresse_api, "cle": garde_api.cle}

    @app.post("/api/api-reseau/cle")
    def api_reseau_cle():
        if garde_api is None:
            return erreur(404, "L'API réseau n'est pas active (API_ACTIVE dans config.py).")
        return {"cle": garde_api.regenerer()}

    @app.post("/api/dossiers/choisir")
    def dossiers_choisir():
        return {"dossier": choisir_dossier() if choisir_dossier else None}

    @app.get("/api/conversations/{identifiant}")
    def conversation(identifiant: str):
        try:
            lue = historique.conversation(identifiant)
            if cowork is None:
                messages, tache = historique.messages(identifiant), {"en_cours": False, "depuis": 0}
            else:  # pris ensemble : les étapes lues + le n° d'où reprendre le flux en direct
                messages, tache = cowork.instantane(identifiant, lambda: historique.messages(identifiant))
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        return {"conversation": asdict(lue), "messages": [asdict(m) for m in messages], "tache": tache}

    @app.delete("/api/conversations/{identifiant}")
    def supprimer(identifiant: str):
        try:
            historique.supprimer(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        if cowork is not None:
            cowork.oublier(identifiant)
        if mediatheque is not None:
            mediatheque.supprimer(identifiant)
        return {"supprimee": True}

    @app.get("/api/medias/{conversation}/{fichier}")
    def media(conversation: str, fichier: str, telecharger: bool = False):
        chemin = mediatheque.chemin(f"{conversation}/{fichier}") if mediatheque else None
        if chemin is None:
            return erreur(404, "Média introuvable (retiré avec sa conversation ?).")
        return reponse_media(chemin, telecharger)

    @app.post("/api/conversations/{identifiant}/messages")
    def envoyer(identifiant: str, demande: NouveauMessage, direct: bool = False):
        """`direct` : la réponse arrive en NDJSON pendant que l'assistant l'écrit (lignes
        « texte », « relais », puis « fin », « erreur » ou « arrete »)."""
        outil = demande.outil
        try:
            pieces = [depuis_base64(p.nom, p.mime, p.donnees) for p in demande.pieces]
        except PieceIllisible as e:
            return erreur(422, str(e))
        try:
            conversation = historique.conversation(identifiant)
            f = fournisseurs.get(conversation.fournisseur)
            if f is None:
                return erreur(409, f"« {conversation.fournisseur} » n'est plus proposé (FOURNISSEURS dans config.py).")
            if outil and outil not in f.outils:
                return erreur(422, f"{f.libelle} ne sait pas créer ça : choisis un modèle Gemini pour une vidéo ou de la musique.")
            precedents = historique.messages(identifiant)
            joints = mediatheque.enregistrer(identifiant, pieces) if mediatheque is not None and pieces else []
            historique.ajouter_message(
                identifiant, "toi", demande.texte, modele=demande.modele, niveau=demande.niveau,
                details=json.dumps({"outil": outil}) if outil else None, medias=joints,
            )
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        limite = repartiteur.limite(outil)
        deja_repondu = any(m.role == "gemini" for m in precedents)
        redondance = reglages.lire()["redondance"] if demande.redondance is None else demande.redondance

        def autres(e: BaseException) -> dict:
            """Sans la redondance, les assistants qu'on peut proposer à la place de celui qui a échoué."""
            if redondance or not peut_basculer(e):
                return {}
            try:
                actuel = historique.conversation(identifiant).fournisseur
            except ConversationInconnue:
                return {}
            return {"autres": repartiteur.suivants(actuel, outil)}

        def rediger(_fournisseur: str, adresse: str | None) -> str:
            # Un assistant qui n'a pas vu la conversation (relais, changement de modèle) en reçoit la transcription.
            base = transcription(precedents, demande.texte) if adresse is None and deja_repondu else demande.texte
            if outil:  # rédigée pour que l'assistant crée le média
                return requete_creation(outil, base, suite=adresse is not None, joints=bool(pieces))
            return base

        def suivre(tentative: Tentative) -> None:
            with verrou_vol:
                en_vol[identifiant] = tentative
            tentative.futur.add_done_callback(lambda _f: liberer(identifiant, tentative))

        deroulement = repartiteur.deroulement(
            identifiant, rediger, demande.modele, demande.niveau, outil, tuple(pieces), demande.redondance,
            apres=lambda resultat, nom: (resultat, enregistrer_reponse(identifiant, resultat, nom)),
            direct=direct, suivre=suivre,
        )
        if direct:
            return StreamingResponse(en_direct(identifiant, deroulement, limite, autres), media_type="application/x-ndjson")
        relais = []
        try:
            for ev in deroulement:
                if ev["type"] == "relais":
                    relais.append(noter_relais(identifiant, ev))
                elif ev["type"] == "fin":
                    resultat, message = ev["retour"]
                    return {"message": message, "medias_perdus": resultat.medias_perdus,
                            "fournisseur": ev["fournisseur"], "relais": relais}
        except CancelledError:
            return {"message": None, "arrete": True}
        except Exception as e:
            return echec(identifiant, *raison_echec(e, limite), **autres(e))

    def en_direct(identifiant: str, deroulement: Iterator[dict], limite: float,
                  autres: Callable[[BaseException], dict]) -> Iterator[str]:
        try:
            for ev in deroulement:
                if ev["type"] == "texte":
                    yield ligne(ev)
                elif ev["type"] == "relais":
                    yield ligne(noter_relais(identifiant, ev))
                elif ev["type"] == "fin":
                    resultat, message = ev["retour"]
                    yield ligne({"type": "fin", "message": message, "medias_perdus": resultat.medias_perdus,
                                 "fournisseur": ev["fournisseur"]})
        except CancelledError:
            yield ligne({"type": "arrete"})
        except Exception as e:
            code, texte_erreur = raison_echec(e, limite)
            noter_erreur(identifiant, texte_erreur)
            yield ligne({"type": "erreur", "code": code, "erreur": texte_erreur, **autres(e)})

    def noter_relais(identifiant: str, ev: dict) -> dict:
        """Gardé dans l'historique : en rouvrant la conversation, on voit qui a pris le relais."""
        note = {"type": "relais", "de": ev["de"], "vers": ev["vers"], "fournisseur": ev["fournisseur"], "raison": ev["raison"]}
        try:
            historique.ajouter_message(identifiant, "relais", f"{ev['de']} → {ev['vers']}", details=json.dumps(note, ensure_ascii=False))
        except ConversationInconnue:
            pass
        return note

    def liberer(identifiant: str, tentative: Tentative) -> None:
        with verrou_vol:
            if en_vol.get(identifiant) is tentative:
                del en_vol[identifiant]

    @app.post("/api/conversations/{identifiant}/arreter")
    def arreter_message(identifiant: str):
        """Arrête le message du Chat en cours : retiré de la file s'il attend son tour, sinon
        l'assistant est interrompu et ce qu'il avait écrit est gardé."""
        with verrou_vol:
            tentative = en_vol.get(identifiant)
        if tentative is None:
            return erreur(409, "Aucune réponse en cours dans cette conversation.")
        tentative.arreter()
        return {"ok": True}

    def raison_echec(e: BaseException, limite: float) -> tuple[int, str]:
        if isinstance(e, DelaiFutur):
            return 504, f"Pas de réponse après {limite:.0f} s."
        if isinstance(e, (ModeleIntrouvable, NiveauIntrouvable, ChoixBloque)):
            for f in fournisseurs.values():
                f.modes.oublier()  # la liste a changé : relue à la prochaine demande
            return 502, str(e)
        if isinstance(e, LimiteAtteinte):
            return 429, str(e)
        if isinstance(e, ErreurPilote):
            return 502, str(e)
        journal.error("Erreur inattendue pendant l'envoi", exc_info=e)
        return 500, f"Erreur inattendue : {e}"

    @app.get("/api/medias")
    def galerie(limite: int = 60, type: str | None = None):
        """Les derniers médias créés par Gemini, toutes conversations confondues."""
        return historique.medias_recents(max(1, min(limite, 500)), type)

    @app.get("/api/conversations/{identifiant}/export")
    def exporter(identifiant: str):
        """La conversation en Markdown, avec ses médias, dans un .zip."""
        try:
            conversation = historique.conversation(identifiant)
            messages = historique.messages(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
            lignes = [f"# {conversation.titre or 'Conversation'}", "", f"_Exportée d'agent.first — {conversation.cree_le}_", ""]
            for m in messages:
                if m.role == "cowork":
                    continue
                if m.role == "relais":
                    lignes += [f"_Relais : {m.texte}_", ""]
                    continue
                assistant = libelle_de(m)
                qui = {"toi": "Toi", "gemini": f"{assistant}{f' ({m.modele})' if m.modele else ''}", "erreur": "Erreur"}.get(m.role, m.role)
                lignes += [f"### {qui} · {m.cree_le}", "", m.texte, ""]
                for media in m.medias:
                    chemin = mediatheque.chemin(media["id"]) if mediatheque else None
                    if chemin is None:
                        continue
                    archive.write(chemin, f"medias/{chemin.name}")
                    nom = media.get("description") or chemin.name
                    lignes += [f"![{nom}](medias/{chemin.name})" if media["type"] == "image" else f"[{nom}](medias/{chemin.name})", ""]
            archive.writestr("conversation.md", "\n".join(lignes))
        nom = re.sub(r"[^\w\- ]", "", conversation.titre or "conversation").strip()[:60] or "conversation"
        return Response(
            tampon.getvalue(), media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=\"agent-first.zip\"; filename*=UTF-8''{quote(nom)}.zip"},
        )

    @app.get("/api/statistiques")
    def statistiques(periode: Periode = "7j"):
        return historique.statistiques(periode)

    def enregistrer_reponse(identifiant: str, resultat: ResultatGemini, fournisseur: str = "gemini") -> dict:
        html = nettoyer_html(resultat.html) if resultat.html else None
        message, _ = garder_reponse(historique, mediatheque, identifiant, resultat, html, fournisseur)
        if message is None:  # conversation retirée pendant l'envoi : la réponse s'affiche quand même
            return {
                "id": None, "conversation_id": identifiant, "role": "gemini", "texte": resultat.reponse,
                "html": html, "modele": resultat.modele, "niveau": resultat.niveau,
                "duree": resultat.duree, "cree_le": None, "medias": [],
            }
        return asdict(message)

    def libelle_de(message) -> str:
        """L'assistant qui a écrit une réponse (noté dans ses détails s'il n'est pas Gemini)."""
        try:
            nom = json.loads(message.details or "{}").get("fournisseur") or "gemini"
        except ValueError:
            nom = "gemini"
        f = fournisseurs.get(nom)
        return f.libelle if f else SITES[nom].libelle if nom in SITES else nom

    def echec(identifiant: str, code: int, message: str, **extra) -> JSONResponse:
        noter_erreur(identifiant, message)
        return JSONResponse(status_code=code, content={"erreur": message, **extra})

    def noter_erreur(identifiant: str, message: str) -> None:
        try:
            historique.ajouter_message(identifiant, "erreur", message)
        except ConversationInconnue:
            pass

    @app.middleware("http")
    async def sans_cache(requete, suite):
        reponse = await suite(requete)
        if not requete.url.path.startswith("/api/"):
            reponse.headers["Cache-Control"] = "no-cache"
        return reponse

    if dossier_web is not None:
        app.mount("/static", StaticFiles(directory=dossier_web), name="static")

        @app.get("/", include_in_schema=False)
        def page():
            return FileResponse(dossier_web / "index.html")

    return app
