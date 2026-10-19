"""API HTTP locale d'Agent First (n'écoute que sur 127.0.0.1)."""
import asyncio
import json
import logging
import threading
import time
from concurrent.futures import TimeoutError as DelaiFutur
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from agent_first.cache_modes import CacheModes
from agent_first.cle_api import GardeCle
from agent_first.cowork_service import TacheEnCours
from agent_first.diffuseur import Diffuseur
from agent_first.etat_google import EtatGoogle
from agent_first.file_attente import FileAttente
from agent_first.fils_serveur import plus_de_fils
from agent_first.historique import ConversationInconnue, Historique
from agent_first.nettoyage import nettoyer_html
from pilote.erreurs import (
    ChoixBloque, ErreurPilote, Interrompu, ModeleIntrouvable, NiveauIntrouvable, PasConnecteGoogle,
)
from pilote.modeles import Modes, ResultatGemini

journal = logging.getLogger(__name__)

INTERVALLE_FLUX = 0.15  # s : au plus un morceau de réponse par intervalle vers la page

Periode = Literal["7j", "30j", "tout"]
INCONNUE = "Conversation inconnue : démarre une nouvelle conversation."
EN_COURS = "Une tâche tourne déjà dans cette conversation : attends sa fin ou arrête-la."


class NouvelleConversation(BaseModel):
    modele: str | None = None
    niveau: str | None = None
    mode: str = "chat"
    dossier: str | None = None


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


class MessageCowork(BaseModel):
    texte: str

    @field_validator("texte")
    @classmethod
    def texte_non_vide(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("le message est vide")
        return valeur


class Renommage(BaseModel):
    titre: str

    @field_validator("titre")
    @classmethod
    def titre_non_vide(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("le titre est vide")
        return valeur


class Decision(BaseModel):
    etape: int
    reponse: str
    toujours: bool = False


def erreur(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"erreur": message})


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
) -> FastAPI:
    """`file_chat` : la file de l'onglet du Chat (messages du Chat, état de Google, modèles) ;
    les tâches Cowork passent par celle du service `cowork`."""
    app = FastAPI(title="Agent First", lifespan=plus_de_fils)
    if hotes_autorises:
        # Une page web ne doit pas pouvoir joindre l'app par « reliure DNS » (et lire la clé de l'API).
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hotes_autorises)
    modes = cache_modes or CacheModes(file_chat, chrome_lance, modes_par_defaut)
    google = EtatGoogle(file_chat, chrome_lance)
    arrets: dict[str, threading.Event] = {}  # réponse en cours (flux) → son bouton Arrêter

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, _exc):
        return erreur(422, "Message vide ou demande invalide.")

    @app.get("/api/etat")
    def etat():
        return {"agent_first": True, "chrome": chrome_lance(), "google": google.lire()}

    @app.get("/api/modeles")
    def modeles():
        return asdict(modes.lire())

    @app.get("/api/conversations")
    def conversations(recherche: str = "", periode: Periode = "tout"):
        return [asdict(c) for c in historique.lister(recherche, periode)]

    @app.post("/api/conversations")
    def nouvelle_conversation(demande: NouvelleConversation | None = None):
        reglages = demande or NouvelleConversation()
        return asdict(
            historique.creer(reglages.modele, reglages.niveau, reglages.mode, reglages.dossier)
        )

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
            cowork.demarrer(identifiant, conv.dossier, conv.adresse, demande.texte, conv.modele, conv.niveau)
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

    @app.patch("/api/conversations/{identifiant}")
    def renommer(identifiant: str, demande: Renommage):
        try:
            historique.renommer(identifiant, demande.titre)
            return asdict(historique.conversation(identifiant))
        except ConversationInconnue:
            return erreur(404, INCONNUE)

    @app.delete("/api/conversations/{identifiant}")
    def supprimer(identifiant: str):
        try:
            historique.supprimer(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        if cowork is not None:
            cowork.oublier(identifiant)
        return {"supprimee": True}

    @app.post("/api/conversations/{identifiant}/messages")
    def envoyer(identifiant: str, demande: NouveauMessage, flux: bool = False):
        """`flux=1` : réponse en NDJSON, une ligne par morceau (`partiel`), puis `message` ou `erreur`."""
        try:
            adresse = historique.conversation(identifiant).adresse
            historique.ajouter_message(identifiant, "toi", demande.texte, modele=demande.modele, niveau=demande.niveau)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        if flux:
            return StreamingResponse(repondre_au_fil(identifiant, adresse, demande), media_type="application/x-ndjson")
        code, corps = traiter(identifiant, adresse, demande)
        return corps if code == 200 else erreur(code, corps["erreur"])

    @app.post("/api/conversations/{identifiant}/arreter")
    def arreter_reponse(identifiant: str):
        arret = arrets.get(identifiant)
        if arret is not None:
            arret.set()
        return {"ok": arret is not None}

    async def repondre_au_fil(identifiant: str, adresse: str | None, demande: NouveauMessage):
        boucle = asyncio.get_running_loop()
        evenements: asyncio.Queue = asyncio.Queue()
        arret = threading.Event()
        arrets[identifiant] = arret
        dernier = {"quand": 0.0, "texte": ""}

        def publier(evenement: dict) -> None:
            try:
                boucle.call_soon_threadsafe(evenements.put_nowait, evenement)
            except RuntimeError:
                pass  # serveur arrêté entre-temps

        def au_fil(texte: str, html: str) -> None:
            if arret.is_set():
                raise Interrompu(texte, html)
            maintenant = time.monotonic()
            if texte.strip() and texte != dernier["texte"] and maintenant - dernier["quand"] >= INTERVALLE_FLUX:
                dernier.update(quand=maintenant, texte=texte)
                publier({"type": "partiel", "texte": texte, "html": nettoyer_html(html) if html else None})

        def travailler() -> None:
            # Dans son propre fil : la réponse est enregistrée même si la page se ferme entre-temps.
            try:
                code, corps = traiter(identifiant, adresse, demande, au_fil, arret)
            finally:
                if arrets.get(identifiant) is arret:
                    del arrets[identifiant]
            publier({"type": "message", **corps} if code == 200 else {"type": "erreur", "code": code, **corps})

        threading.Thread(target=travailler, name=f"reponse-{identifiant[:8]}", daemon=True).start()
        while True:
            evenement = await evenements.get()
            yield json.dumps(evenement, ensure_ascii=False) + "\n"
            if evenement["type"] != "partiel":
                return

    def traiter(identifiant: str, adresse: str | None, demande: NouveauMessage, au_fil=None,
                arret: threading.Event | None = None) -> tuple[int, dict]:
        """Envoie le message, attend la réponse et l'enregistre (ou l'erreur) : (code HTTP, corps)."""

        def travail(pilote):
            if arret is not None and arret.is_set():  # arrêté pendant qu'il attendait son tour
                raise Interrompu()
            if au_fil is None:
                return pilote.envoyer(adresse, demande.texte, demande.modele, demande.niveau)
            return pilote.envoyer(adresse, demande.texte, demande.modele, demande.niveau, au_fil=au_fil)

        debut = time.monotonic()
        futur = file_chat.soumettre(travail)
        try:
            resultat = futur.result(timeout=delai)
        except DelaiFutur:
            futur.cancel()
            if arret is not None:
                arret.set()  # que Gemini s'arrête aussi : la réponse ne sera plus attendue
            return echec(identifiant, 504, f"Pas de réponse de Gemini après {delai:.0f} s.")
        except Interrompu as e:
            if not e.partiel:
                return echec(identifiant, 499, "Réponse arrêtée avant son début.")
            interrompue = ResultatGemini(e.partiel, adresse or "", e.html, demande.modele, demande.niveau,
                                         round(time.monotonic() - debut, 1))
            return 200, {"message": enregistrer_reponse(identifiant, interrompue, interrompue=True)}
        except (ModeleIntrouvable, NiveauIntrouvable, ChoixBloque) as e:
            modes.oublier()  # la liste a changé : relue à la prochaine demande
            return echec(identifiant, 502, str(e))
        except PasConnecteGoogle as e:
            google.noter(False)
            return echec(identifiant, 502, str(e))
        except ErreurPilote as e:
            return echec(identifiant, 502, str(e))
        except Exception as e:
            journal.exception("Erreur inattendue pendant l'envoi")
            return echec(identifiant, 500, f"Erreur inattendue : {e}")
        google.noter(True)
        return 200, {"message": enregistrer_reponse(identifiant, resultat)}

    @app.get("/api/statistiques")
    def statistiques(periode: Periode = "7j"):
        return historique.statistiques(periode)

    def enregistrer_reponse(identifiant: str, resultat: ResultatGemini, interrompue: bool = False) -> dict:
        html = nettoyer_html(resultat.html) if resultat.html else None
        details = json.dumps({"interrompue": True}) if interrompue else None
        try:
            if resultat.adresse:
                historique.enregistrer_adresse(identifiant, resultat.adresse)
            message = historique.ajouter_message(
                identifiant, "gemini", resultat.reponse, html=html,
                modele=resultat.modele, niveau=resultat.niveau, duree=resultat.duree, details=details,
            )
        except ConversationInconnue:
            journal.info("Conversation %s supprimée pendant l'envoi : réponse non enregistrée", identifiant)
            return {
                "id": None, "conversation_id": identifiant, "role": "gemini", "texte": resultat.reponse,
                "html": html, "modele": resultat.modele, "niveau": resultat.niveau,
                "duree": resultat.duree, "details": details, "fournisseur": None, "cree_le": None,
            }
        return asdict(message)

    def echec(identifiant: str, code: int, message: str) -> tuple[int, dict]:
        try:
            historique.ajouter_message(identifiant, "erreur", message)
        except ConversationInconnue:
            pass
        return code, {"erreur": message}

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
