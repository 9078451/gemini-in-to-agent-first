"""L'API réseau d'Agent First : d'autres programmes (sur ce PC ou sur le réseau)
discutent avec Gemini au format OpenAI, ou lancent et suivent des tâches Cowork.

Elle écoute sur un port à part (8766, toutes les interfaces) ; chaque route `/v1`
exige la clé (`Authorization: Bearer …`). L'app, elle, reste sur 127.0.0.1:8765.
La documentation interactive est sur `/docs`.
"""
import json
import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import TimeoutError as DelaiFutur
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as ExceptionHttp

from agent_first.cache_modes import CacheModes
from agent_first.cle_api import GardeCle
from agent_first.cowork_service import ServiceCowork, TacheEnCours
from agent_first.file_attente import FileAttente
from agent_first.historique import ConversationInconnue, Historique
from agent_first.openai_compat import (
    completion,
    empreinte,
    mettre_a_plat,
    morceaux,
    nettoyer_reponse,
    niveau_depuis_effort,
    texte_message,
    vers_api,
)
from pilote.erreurs import ChoixBloque, ErreurPilote, ModeleIntrouvable, NiveauIntrouvable

journal = logging.getLogger(__name__)

CONVERSATIONS_MEMORISEES = 500
TYPES_ERREUR = {
    400: "invalid_request_error", 401: "authentication_error", 404: "not_found_error", 409: "conflict_error",
    429: "rate_limit_error", 500: "server_error", 502: "upstream_error", 504: "timeout_error",
}
MESSAGES_CLE = {401: "Missing or invalid API key (Authorization: Bearer <key>).",
                429: "Too many invalid keys from this address: try again in a minute."}
MODELE_PAR_DEFAUT = "agent-first"  # = le modèle déjà choisi dans Gemini


class DemandeChat(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str | None = None
    messages: list[dict]
    stream: bool = False
    reasoning_effort: str | None = None


class NouvelleTache(BaseModel):
    folder: str
    request: str
    model: str | None = None
    reasoning_effort: str | None = None


class MessageTache(BaseModel):
    text: str


class DecisionTache(BaseModel):
    step: int
    approve: bool
    always: bool = False


def creer_api_reseau(
    file: FileAttente,
    historique: Historique,
    cowork: ServiceCowork,
    garde: GardeCle,
    modes: CacheModes,
    delai: float,
    niveau_cowork: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Agent First — API réseau",
        description="Gemini au format OpenAI (`/v1/chat/completions`) et tâches Cowork (`/v1/cowork`). "
        "Chaque appel exige `Authorization: Bearer <clé>` (clé dans Paramètres de l'app).",
        version="3",
    )
    memoire: OrderedDict[str, tuple[str, str]] = OrderedDict()  # empreinte → (conversation, adresse Gemini)
    verrou = threading.Lock()

    # Celle de Starlette (parente de celle de FastAPI) : corps illisible, route inconnue… aussi au format OpenAI.
    @app.exception_handler(ExceptionHttp)
    def erreur_http(_requete, exc: ExceptionHttp):
        return _erreur(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, exc: RequestValidationError):
        return _erreur(400, f"Invalid request: {exc.errors()[0].get('msg', 'bad body')}")

    def authentifier(requete: Request) -> None:
        adresse = requete.client.host if requete.client else "?"
        code = garde.verifier(adresse, requete.headers.get("authorization"))
        if code is not None:
            raise HTTPException(code, MESSAGES_CLE[code])

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(authentifier)])

    # ---- format OpenAI -------------------------------------------------

    @v1.get("/models")
    def modeles():
        lus = modes.lire()
        return {
            "object": "list",
            "data": [
                {"id": o.nom, "object": "model", "created": 0, "owned_by": "google-gemini", "description": o.description}
                for o in lus.modeles
            ],
        }

    @v1.post("/chat/completions")
    def chat(demande: DemandeChat):
        if not any(m.get("role") == "user" for m in demande.messages):
            raise HTTPException(400, "messages must contain at least one user message")
        modele = demande.model if demande.model and demande.model != MODELE_PAR_DEFAUT else None
        niveau = niveau_depuis_effort(demande.reasoning_effort)
        dernier = texte_message(demande.messages[-1].get("content"))
        with verrou:
            connue = memoire.get(empreinte(modele, demande.messages[:-1])) if len(demande.messages) > 1 else None
        if connue:
            conversation_id, adresse, texte = connue[0], connue[1], dernier
        else:
            conversation_id, adresse = historique.creer(modele, niveau, "chat", None, source="api").id, None
            texte = mettre_a_plat(demande.messages)
        _noter(conversation_id, "toi", dernier, modele=modele, niveau=niveau)
        futur = file.soumettre(lambda pilote: pilote.envoyer(adresse, texte, modele, niveau))
        try:
            resultat = futur.result(timeout=delai)
        except DelaiFutur:
            raise HTTPException(504, f"No answer from Gemini after {delai:.0f} s (Agent First may be busy).")
        except (ModeleIntrouvable, NiveauIntrouvable, ChoixBloque) as e:
            modes.oublier()
            raise HTTPException(400, str(e))
        except ErreurPilote as e:
            raise HTTPException(502, str(e))
        except Exception as e:
            journal.exception("Erreur inattendue pendant un appel de l'API réseau")
            raise HTTPException(500, f"Unexpected error: {e}")
        contenu = nettoyer_reponse(resultat.reponse)
        try:
            historique.enregistrer_adresse(conversation_id, resultat.adresse)
        except ConversationInconnue:
            pass  # retirée de l'historique entre-temps : la réponse part quand même
        _noter(conversation_id, "gemini", contenu, modele=resultat.modele, niveau=resultat.niveau, duree=resultat.duree)
        suite = demande.messages + [{"role": "assistant", "content": contenu}]
        with verrou:
            memoire[empreinte(modele, suite)] = (conversation_id, resultat.adresse)
            while len(memoire) > CONVERSATIONS_MEMORISEES:
                memoire.popitem(last=False)
        nom = resultat.modele or modele or MODELE_PAR_DEFAUT
        if demande.stream:
            return StreamingResponse(morceaux(contenu, nom), media_type="text/event-stream")
        return completion(contenu, nom, texte)

    def _noter(conversation_id: str, role: str, texte: str, **details) -> None:
        try:
            historique.ajouter_message(conversation_id, role, texte, **details)
        except ConversationInconnue:
            pass

    # ---- Cowork --------------------------------------------------------

    @v1.post("/cowork")
    def cowork_creer(demande: NouvelleTache):
        refus = _dossier_refuse(demande.folder)
        if refus:
            raise HTTPException(400, refus)
        # Sans niveau demandé : celui de l'app (Min.). Gemini garderait son réglage, souvent « Max. »,
        # qui abandonne une longue demande Cowork sans répondre (vu en essai réel).
        niveau = niveau_depuis_effort(demande.reasoning_effort) or niveau_cowork
        modele = demande.model if demande.model and demande.model != MODELE_PAR_DEFAUT else None
        dossier = str(Path(demande.folder).resolve())
        conversation = historique.creer(modele, niveau, "cowork", dossier, source="api")
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
        historique.ajouter_message(identifiant, "toi", texte)
        try:
            cowork.demarrer(identifiant, conversation.dossier, conversation.adresse, texte,
                            conversation.modele, conversation.niveau)
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
    return app


def _erreur(code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={"error": {"message": message, "type": TYPES_ERREUR.get(code, "error"), "code": code}},
    )


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
