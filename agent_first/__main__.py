"""Lance Agent First : python -m agent_first [--ouvrir]"""
import argparse
import logging
import threading

import uvicorn

import config
from agent_first.api_reseau import creer_api_reseau
from agent_first.cache_modes import CacheModes
from agent_first.cle_api import GardeCle
from agent_first.cowork_service import ServiceCowork
from agent_first.diffuseur import Diffuseur
from agent_first.dossier import choisir_dossier
from agent_first.fenetre import ouvrir_quand_pret, repond
from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from agent_first.openai_compat import adresse_reseau
from agent_first.serveur import creer_app
from cowork.actions import Executeur
from cowork.boucle import Reglages
from cowork.processus import GestionnaireProcessus
from pilote.chrome import ChromeDedie
from pilote.gemini import PiloteGemini
from pilote.modeles import Modes, Option


def main() -> None:
    parser = argparse.ArgumentParser(description="Lance Agent First.")
    parser.add_argument("--ouvrir", action="store_true", help="ouvre l'app dans une fenêtre Chrome")
    args = parser.parse_args()

    config.DOSSIER_JOURNAUX.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s",
        handlers=[
            logging.FileHandler(config.DOSSIER_JOURNAUX / "agent_first.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    # est_lance() est appelé depuis les fils du serveur ; page() seulement
    # depuis le fil de la file d'attente (via le pilote).
    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)

    def fabrique_pilote() -> PiloteGemini:
        return PiloteGemini(
            chrome, config.URL_GEMINI, config.DELAI_REPONSE, config.STABILITE, config.DOSSIER_JOURNAUX
        )

    file = FileAttente(fabrique_pilote)
    file.demarrer()
    historique = Historique(config.FICHIER_HISTORIQUE)
    par_defaut = Modes(
        [Option(n, d, n == config.MODELE_ACTIF_PAR_DEFAUT) for n, d in config.MODELES_PAR_DEFAUT],
        [Option(n, d, n == config.NIVEAU_ACTIF_PAR_DEFAUT) for n, d in config.NIVEAUX_PAR_DEFAUT],
    )
    # Gemini ne doit pas pouvoir joindre Agent First (il validerait ses propres accords) ni le Chrome dédié.
    ports_interdits = frozenset({config.PORT_AGENT, config.PORT_API, config.PORT_CHROME})

    def fabrique_executeur(dossier, processus, arret):
        return Executeur(
            dossier, config.DELAI_COMMANDE, config.TAILLE_MAX_SORTIE, processus=processus,
            ports_interdits=ports_interdits, delai_visite=config.DELAI_VISITE, arret=arret,
        )

    def fabrique_processus(dossier, au_changement):
        return GestionnaireProcessus(
            dossier, config.MAX_PROCESSUS, config.ATTENTE_DEMARRAGE, config.TAILLE_MAX_SORTIE,
            au_changement=au_changement,
        )

    reglages = Reglages(
        max_tours=config.MAX_TOURS_COWORK, max_actions=config.MAX_ACTIONS_PAR_MESSAGE,
        echecs_max=config.ECHECS_FORMAT_MAX, taille_max=config.TAILLE_MAX_SORTIE,
        taille_max_message=config.TAILLE_MAX_MESSAGE, relances_fin_max=config.RELANCES_FIN_MAX,
    )
    diffuseur = Diffuseur()
    cache_modes = CacheModes(file, chrome.est_lance, par_defaut)
    cowork = ServiceCowork(
        file, historique, fabrique_executeur, reglages, fabrique_processus,
        delai_accord=config.DELAI_ACCORD, delai_reponse=config.DELAI_REPONSE_COWORK,
        diffuseur=diffuseur, max_entrees=config.MAX_ENTREES_ARBORESCENCE,
    )
    garde, adresse_api, serveur_api = None, None, None
    if config.API_ACTIVE:
        garde = GardeCle(config.FICHIER_CLE_API, essais_max=config.ESSAIS_CLE_MAX)
        adresse_api = f"http://{adresse_reseau()}:{config.PORT_API}/v1"
        api = creer_api_reseau(file, historique, cowork, garde, cache_modes, config.DELAI_AGENT)
        serveur_api = uvicorn.Server(uvicorn.Config(api, host=config.HOTE_API, port=config.PORT_API, log_level="warning", timeout_graceful_shutdown=3))
        threading.Thread(target=serveur_api.run, name="api-reseau", daemon=True).start()
        logging.getLogger("agent_first").info("API réseau : %s (clé dans Paramètres ou %s)", adresse_api, config.FICHIER_CLE_API)
    app = creer_app(
        file, historique, config.DELAI_AGENT, chrome.est_lance, par_defaut,
        config.DOSSIER_WEB, cowork=cowork, choisir_dossier=choisir_dossier,
        diffuseur=diffuseur, cache_modes=cache_modes, garde_api=garde, adresse_api=adresse_api,
    )
    if args.ouvrir:
        url = f"http://{config.HOTE_AGENT}:{config.PORT_AGENT}/"
        threading.Thread(
            target=ouvrir_quand_pret, args=(config.CHEMIN_CHROME, url, lambda: repond(url)), daemon=True
        ).start()
    try:
        # Les flux en direct (SSE) restent ouverts tant que l'app est affichée : sans délai, l'arrêt les attendrait.
        uvicorn.run(app, host=config.HOTE_AGENT, port=config.PORT_AGENT, timeout_graceful_shutdown=3)
    finally:
        if serveur_api is not None:
            serveur_api.should_exit = True
        cowork.arreter_tout()  # les serveurs lancés par Cowork s'arrêtent avec Agent First
        file.arreter()


if __name__ == "__main__":
    main()
