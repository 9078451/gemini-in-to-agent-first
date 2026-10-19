"""API HTTP locale d'Agent First (n'écoute que sur 127.0.0.1)."""
import json
import logging
import threading
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
from agent_first.discussion import EchecEnvoi, ServiceChat
from agent_first.en_direct import en_direct
from agent_first.etat_google import EtatGoogle
from agent_first.file_attente import FileAttente
from agent_first.fils_serveur import plus_de_fils
from agent_first.historique import ConversationInconnue, Historique
from agent_first.nettoyage import nettoyer_html
from fournisseurs.catalogue import CATALOGUE, PAR_DEFAUT, WEB
from fournisseurs.reglages import ReglagesFournisseurs
from fournisseurs.repartiteur import Repartiteur
from fournisseurs.service import ServiceFournisseurs
from pilote.chrome import ONGLET_CHAT
from pilote.erreurs import ErreurPilote, PasConnecteGoogle
from pilote.modeles import Modes

journal = logging.getLogger(__name__)

Periode = Literal["7j", "30j", "tout"]
INCONNUE = "Conversation inconnue : démarre une nouvelle conversation."
EN_COURS = "Une tâche tourne déjà dans cette conversation : attends sa fin ou arrête-la."
INCONNU = "Fournisseur inconnu."


def _non_vide(valeur: str) -> str:
    if not valeur.strip():
        raise ValueError("vide")
    return valeur


class NouvelleConversation(BaseModel):
    modele: str | None = None
    niveau: str | None = None
    mode: str = "chat"
    dossier: str | None = None
    fournisseur: str = PAR_DEFAUT


class NouveauMessage(BaseModel):
    texte: str
    fournisseur: str | None = None
    modele: str | None = None
    niveau: str | None = None

    _texte = field_validator("texte")(_non_vide)


class MessageCowork(BaseModel):
    texte: str
    fournisseur: str | None = None
    modele: str | None = None
    niveau: str | None = None

    _texte = field_validator("texte")(_non_vide)


class Renommage(BaseModel):
    titre: str

    _titre = field_validator("titre")(_non_vide)


class Decision(BaseModel):
    etape: int
    reponse: str
    toujours: bool = False


class ReglageFournisseur(BaseModel):
    actif: bool | None = None
    cle: str | None = None
    modeles: list[str] | None = None
    url: str | None = None


class ReglageSecours(BaseModel):
    actif: bool
    fournisseur: str | None = None
    modele: str | None = None


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
    fournisseurs: ServiceFournisseurs | None = None,
) -> FastAPI:
    """`file_chat` : la file de l'onglet du Chat de Gemini (état de Google, modèles) ;
    `fournisseurs` donne celles des autres (sans lui : Gemini seul)."""
    app = FastAPI(title="Agent First", lifespan=plus_de_fils)
    if hotes_autorises:
        # Une page web ne doit pas pouvoir joindre l'app par « reliure DNS » (et lire les clés).
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hotes_autorises)
    modes = cache_modes or CacheModes(file_chat, chrome_lance, modes_par_defaut)
    if fournisseurs is None:
        fournisseurs = ServiceFournisseurs(ReglagesFournisseurs(None), Repartiteur.unique(PAR_DEFAUT, ONGLET_CHAT, file_chat), modes)
    reglages = fournisseurs.reglages
    google = EtatGoogle(file_chat, chrome_lance)

    def noter(fournisseur: str, erreur_envoi: Exception | None) -> None:
        if fournisseur == PAR_DEFAUT and erreur_envoi is None:
            google.noter(True)
        elif isinstance(erreur_envoi, PasConnecteGoogle):
            google.noter(False)

    chat = ServiceChat(historique, fournisseurs, delai, noter)
    arrets: dict[str, threading.Event] = {}  # réponse en cours (flux) → son bouton Arrêter

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, _exc):
        return erreur(422, "Message vide ou demande invalide.")

    @app.get("/api/etat")
    def etat():
        return {"agent_first": True, "chrome": chrome_lance(), "google": google.lire(),
                "fournisseurs": fournisseurs.etats.tous(fournisseurs.actifs())}

    @app.get("/api/modeles")
    def modeles():
        return asdict(modes.lire())

    # ---- fournisseurs -------------------------------------------------------

    def etat_fournisseurs() -> dict:
        return {"actifs": fournisseurs.liste(), "tous": reglages.publics(), "secours": reglages.secours()}

    @app.get("/api/fournisseurs")
    def lister_fournisseurs():
        return etat_fournisseurs()

    @app.put("/api/fournisseurs/{identifiant}")
    def regler_fournisseur(identifiant: str, demande: ReglageFournisseur):
        if identifiant not in CATALOGUE:
            return erreur(404, INCONNU)
        if identifiant == PAR_DEFAUT and demande.actif is False:
            return erreur(422, "Gemini reste actif : c'est le fournisseur par défaut.")
        reglages.enregistrer(identifiant, actif=demande.actif, cle=demande.cle, modeles=demande.modeles, url=demande.url)
        if demande.cle is not None or demande.url is not None or demande.actif:
            fournisseurs.oublier_modeles(identifiant)  # nouvelle clé ou adresse : la liste sera relue
        return etat_fournisseurs()

    @app.post("/api/fournisseurs/{identifiant}/modeles")
    def lire_modeles(identifiant: str):
        if not fournisseurs.est_actif(identifiant):
            return erreur(404, "Active d'abord ce fournisseur.")
        try:
            return {"modeles": fournisseurs.lire_modeles(identifiant)}
        except ErreurPilote as e:
            return erreur(502, str(e))
        except Exception as e:
            journal.warning("Modèles de %s illisibles", identifiant, exc_info=True)
            return erreur(502, f"Liste illisible : {e}")

    @app.post("/api/fournisseurs/{identifiant}/ouvrir")
    def ouvrir_site(identifiant: str):
        """Ouvre l'onglet du site dans le Chrome dédié, pour s'y connecter."""
        if identifiant not in CATALOGUE or CATALOGUE[identifiant].type != WEB:
            return erreur(404, "Ce fournisseur n'est pas un site.")
        if not fournisseurs.est_actif(identifiant):
            return erreur(404, "Active d'abord ce fournisseur.")
        fournisseurs.repartiteur.file(identifiant, ONGLET_CHAT).soumettre(lambda pilote: pilote.ouvrir())
        return {"ok": True}

    @app.put("/api/secours")
    def regler_secours(demande: ReglageSecours):
        if demande.fournisseur is not None and demande.fournisseur not in CATALOGUE:
            return erreur(404, INCONNU)
        reglages.regler_secours(demande.actif, demande.fournisseur, demande.modele)
        return etat_fournisseurs()

    # ---- conversations ----------------------------------------------------

    @app.get("/api/conversations")
    def conversations(recherche: str = "", periode: Periode = "tout"):
        return [asdict(c) for c in historique.lister(recherche, periode)]

    @app.post("/api/conversations")
    def nouvelle_conversation(demande: NouvelleConversation | None = None):
        r = demande or NouvelleConversation()
        if r.fournisseur not in CATALOGUE:
            return erreur(404, INCONNU)
        return asdict(historique.creer(r.modele, r.niveau, r.mode, r.dossier, fournisseur=r.fournisseur))

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
        if demande.fournisseur and demande.fournisseur != conv.fournisseur:
            historique.changer_fournisseur(identifiant, demande.fournisseur, demande.modele, demande.niveau)
            conv = historique.conversation(identifiant)
        elif demande.modele or demande.niveau:
            historique.regler_modele(identifiant, demande.modele or conv.modele, demande.niveau or conv.niveau)
            conv = historique.conversation(identifiant)
        try:  # le service enregistre le message s'il accepte la tâche
            cowork.demarrer(identifiant, conv.dossier, conv.adresse, demande.texte, conv.modele, conv.niveau,
                            fournisseur=conv.fournisseur)
        except TacheEnCours:
            return erreur(409, EN_COURS)
        except ErreurPilote as e:  # fournisseur désactivé entre-temps
            return erreur(400, str(e))
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
        return {"conversation": asdict(lue), "messages": [asdict(m) for m in messages], "tache": tache,
                "en_cours": identifiant in arrets}

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
            historique.conversation(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        if not flux:
            code, corps = traiter(identifiant, demande)
            return corps if code == 200 else erreur(code, corps["erreur"])
        arret = threading.Event()
        arrets[identifiant] = arret

        def travail(au_fil) -> dict:
            def au_fil_nettoye(texte: str, html: str) -> None:
                au_fil(texte, nettoyer_html(html) if html else "")

            try:
                code, corps = traiter(identifiant, demande, au_fil_nettoye, arret)
            finally:
                if arrets.get(identifiant) is arret:
                    del arrets[identifiant]
            return {"type": "message", **corps} if code == 200 else {"type": "erreur", "code": code, **corps}

        lignes = (json.dumps(ev, ensure_ascii=False) + "\n" for ev in en_direct(travail, arret, nom=f"reponse-{identifiant[:8]}"))
        return StreamingResponse(lignes, media_type="application/x-ndjson")

    @app.post("/api/conversations/{identifiant}/arreter")
    def arreter_reponse(identifiant: str):
        arret = arrets.get(identifiant)
        if arret is not None:
            arret.set()
        return {"ok": arret is not None}

    def traiter(identifiant: str, demande: NouveauMessage, au_fil=None,
                arret: threading.Event | None = None) -> tuple[int, dict]:
        """Envoie le message, attend la réponse et l'enregistre (ou l'erreur) : (code HTTP, corps)."""
        try:
            message = chat.envoyer(identifiant, demande.texte, demande.fournisseur, demande.modele, demande.niveau,
                                   au_fil=au_fil, arret=arret)
        except ConversationInconnue:
            return 404, {"erreur": INCONNUE}
        except EchecEnvoi as e:
            return e.code, {"erreur": e.message}
        return 200, {"message": message}

    @app.get("/api/statistiques")
    def statistiques(periode: Periode = "7j"):
        return historique.statistiques(periode)

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
