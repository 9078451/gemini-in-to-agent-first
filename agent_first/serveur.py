"""API HTTP locale d'Agent First (n'écoute que sur 127.0.0.1)."""
import logging
from concurrent.futures import TimeoutError as DelaiFutur
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from agent_first.file_attente import FileAttente
from agent_first.historique import ConversationInconnue, Historique
from agent_first.nettoyage import nettoyer_html
from pilote.erreurs import ErreurPilote, ModeleIntrouvable, NiveauIntrouvable
from pilote.modeles import Modes, ResultatGemini

journal = logging.getLogger(__name__)

Periode = Literal["7j", "30j", "tout"]
INCONNUE = "Conversation inconnue : démarre une nouvelle conversation."


class NouvelleConversation(BaseModel):
    modele: str | None = None
    niveau: str | None = None


class NouveauMessage(BaseModel):
    texte: str
    modele: str | None = None
    niveau: str | None = None

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
    historique: Historique,
    delai: float,
    chrome_lance: Callable[[], bool],
    modes_par_defaut: Modes,
    dossier_web: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Agent First")
    cache: dict[str, Modes] = {}

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, _exc):
        return erreur(422, "Message vide ou demande invalide.")

    @app.get("/api/etat")
    def etat():
        lance = chrome_lance()
        google = None
        if lance:
            try:
                google = file.soumettre(lambda pilote: pilote.est_connecte()).result(timeout=5)
            except Exception:
                google = None  # occupé ou injoignable : inconnu
        return {"agent_first": True, "chrome": lance, "google": google}

    @app.get("/api/modeles")
    def modeles():
        modes = cache.get("modes")
        if modes is None and chrome_lance():
            try:
                lus = file.soumettre(lambda pilote: pilote.lister_modes()).result(timeout=30)
                if lus.modeles:
                    cache["modes"] = modes = lus
            except Exception:
                journal.warning("Modèles illisibles dans Gemini : liste par défaut", exc_info=True)
        return asdict(modes or modes_par_defaut)

    @app.get("/api/conversations")
    def conversations(recherche: str = "", periode: Periode = "tout"):
        return [asdict(c) for c in historique.lister(recherche, periode)]

    @app.post("/api/conversations")
    def nouvelle_conversation(demande: NouvelleConversation | None = None):
        reglages = demande or NouvelleConversation()
        return asdict(historique.creer(reglages.modele, reglages.niveau))

    @app.get("/api/conversations/{identifiant}")
    def conversation(identifiant: str):
        try:
            lue = historique.conversation(identifiant)
            messages = historique.messages(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        return {"conversation": asdict(lue), "messages": [asdict(m) for m in messages]}

    @app.delete("/api/conversations/{identifiant}")
    def supprimer(identifiant: str):
        try:
            historique.supprimer(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        return {"supprimee": True}

    @app.post("/api/conversations/{identifiant}/messages")
    def envoyer(identifiant: str, demande: NouveauMessage):
        try:
            adresse = historique.conversation(identifiant).adresse
            historique.ajouter_message(identifiant, "toi", demande.texte, modele=demande.modele, niveau=demande.niveau)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        futur = file.soumettre(lambda pilote: pilote.envoyer(adresse, demande.texte, demande.modele, demande.niveau))
        try:
            resultat = futur.result(timeout=delai)
        except DelaiFutur:
            return echec(identifiant, 504, f"Pas de réponse de Gemini après {delai:.0f} s.")
        except (ModeleIntrouvable, NiveauIntrouvable) as e:
            cache.pop("modes", None)  # la liste a changé : relue à la prochaine demande
            return echec(identifiant, 502, str(e))
        except ErreurPilote as e:
            return echec(identifiant, 502, str(e))
        except Exception as e:
            journal.exception("Erreur inattendue pendant l'envoi")
            return echec(identifiant, 500, f"Erreur inattendue : {e}")
        return {"message": enregistrer_reponse(identifiant, resultat)}

    @app.get("/api/statistiques")
    def statistiques(periode: Periode = "7j"):
        return historique.statistiques(periode)

    def enregistrer_reponse(identifiant: str, resultat: ResultatGemini) -> dict:
        html = nettoyer_html(resultat.html) if resultat.html else None
        try:
            historique.enregistrer_adresse(identifiant, resultat.adresse)
            message = historique.ajouter_message(
                identifiant, "gemini", resultat.reponse, html=html,
                modele=resultat.modele, niveau=resultat.niveau, duree=resultat.duree,
            )
        except ConversationInconnue:
            journal.info("Conversation %s supprimée pendant l'envoi : réponse non enregistrée", identifiant)
            return {
                "id": None, "conversation_id": identifiant, "role": "gemini", "texte": resultat.reponse,
                "html": html, "modele": resultat.modele, "niveau": resultat.niveau,
                "duree": resultat.duree, "cree_le": None,
            }
        return asdict(message)

    def echec(identifiant: str, code: int, message: str) -> JSONResponse:
        try:
            historique.ajouter_message(identifiant, "erreur", message)
        except ConversationInconnue:
            pass
        return erreur(code, message)

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
