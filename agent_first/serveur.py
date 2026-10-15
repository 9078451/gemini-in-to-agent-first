"""API HTTP locale d'Agent First (n'écoute que sur 127.0.0.1)."""
import logging
from concurrent.futures import TimeoutError as DelaiFutur
from typing import Callable

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from agent_first.conversations import ConversationInconnue, MemoireConversations
from agent_first.file_attente import FileAttente
from pilote.erreurs import ErreurPilote

journal = logging.getLogger(__name__)


class DemandeMessage(BaseModel):
    conversation: str
    texte: str

    @field_validator("texte")
    @classmethod
    def texte_non_vide(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("le message est vide")
        return valeur


def erreur(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"erreur": message})


def creer_app(
    file: FileAttente,
    memoire: MemoireConversations,
    delai: float,
    chrome_lance: Callable[[], bool],
) -> FastAPI:
    app = FastAPI(title="Agent First")

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, _exc):
        return erreur(422, "Message vide ou invalide.")

    @app.post("/conversations")
    def nouvelle_conversation():
        return {"conversation": memoire.creer()}

    @app.post("/message")
    def message(demande: DemandeMessage):
        try:
            adresse = memoire.adresse(demande.conversation)
        except ConversationInconnue:
            return erreur(404, "Conversation inconnue : démarre une nouvelle conversation.")
        futur = file.soumettre(lambda pilote: pilote.envoyer(adresse, demande.texte))
        try:
            resultat = futur.result(timeout=delai)
        except DelaiFutur:
            return erreur(504, f"Pas de réponse de Gemini après {delai:.0f} s.")
        except ErreurPilote as e:
            return erreur(502, str(e))
        except Exception as e:
            journal.exception("Erreur inattendue pendant l'envoi")
            return erreur(500, f"Erreur inattendue : {e}")
        memoire.enregistrer(demande.conversation, resultat.adresse)
        return {"conversation": demande.conversation, "reponse": resultat.reponse}

    @app.get("/etat")
    def etat():
        lance = chrome_lance()
        google = None
        if lance:
            try:
                google = file.soumettre(lambda pilote: pilote.est_connecte()).result(timeout=5)
            except Exception:
                google = None  # occupé ou injoignable : inconnu
        return {"agent_first": True, "chrome": lance, "google": google}

    return app
