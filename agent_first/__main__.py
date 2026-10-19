"""Lance Agent First : python -m agent_first [--ouvrir]"""
import argparse
import logging
import threading

import uvicorn

import config
from agent_first.assemblage import assembler
from agent_first.dossier import choisir_dossier
from agent_first.fenetre import ouvrir_quand_pret, repond
from agent_first.historique import Historique
from agent_first.openai_compat import adresse_reseau
from fournisseurs.fabriques import fabriques_api, ids_api
from fournisseurs.memoire import MemoireFils
from fournisseurs.reglages import ReglagesFournisseurs
from pilote.chrome import ONGLET_COWORK, ChromeDedie, OngletGemini, OngletSite
from pilote.gemini import PiloteGemini, ReglagesCompte
from pilote.site import PiloteSite
from pilote.sites import PROFILS


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
    # est_lance() est appelé depuis les fils du serveur ; chaque onglet (page) seulement
    # depuis le fil de sa file d'attente (via son pilote).
    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    reglages_compte = ReglagesCompte()  # les deux onglets partagent le compte Google

    def fabrique_pilote(role: str) -> PiloteGemini:
        return PiloteGemini(
            OngletGemini(chrome, role, principal=role == ONGLET_COWORK),
            config.URL_GEMINI, config.DELAI_REPONSE, config.STABILITE, config.DOSSIER_JOURNAUX,
            reglages=reglages_compte,
        )

    def fabrique_site(identifiant: str):
        profil = PROFILS[identifiant]
        return lambda role: PiloteSite(
            OngletSite(chrome, role, url_accueil=profil.url_nouvelle, prefixe=profil.prefixe),
            profil, config.DELAI_REPONSE, config.STABILITE, config.DOSSIER_JOURNAUX,
        )

    reglages = ReglagesFournisseurs(config.FICHIER_FOURNISSEURS)
    memoire = MemoireFils(config.FICHIER_FILS)
    fabriques = {**fabriques_api(reglages, memoire), **{i: fabrique_site(i) for i in PROFILS}}
    adresse_api = f"http://{adresse_reseau()}:{config.PORT_API}/v1" if config.API_ACTIVE else None
    agent = assembler(
        fabrique_pilote, chrome.est_lance, Historique(config.FICHIER_HISTORIQUE),
        config.FICHIER_CLE_API if config.API_ACTIVE else None,
        adresse_api=adresse_api, choisir_dossier=choisir_dossier,
        reglages=reglages, fabriques_autres=fabriques, paralleles=ids_api(),
    )
    serveur_api = None
    if agent.api is not None:
        serveur_api = uvicorn.Server(uvicorn.Config(agent.api, host=config.HOTE_API, port=config.PORT_API, log_level="warning", timeout_graceful_shutdown=3))
        threading.Thread(target=serveur_api.run, name="api-reseau", daemon=True).start()
        logging.getLogger("agent_first").info("API réseau : %s (clé dans Paramètres ou %s)", adresse_api, config.FICHIER_CLE_API)
    if args.ouvrir:
        url = f"http://{config.HOTE_AGENT}:{config.PORT_AGENT}/"
        threading.Thread(
            target=ouvrir_quand_pret, args=(config.CHEMIN_CHROME, url, lambda: repond(url)), daemon=True
        ).start()
    try:
        # Les flux en direct (SSE) restent ouverts tant que l'app est affichée : sans délai, l'arrêt les attendrait.
        uvicorn.run(agent.app, host=config.HOTE_AGENT, port=config.PORT_AGENT, timeout_graceful_shutdown=3)
    finally:
        if serveur_api is not None:
            serveur_api.should_exit = True
        agent.arreter()


if __name__ == "__main__":
    main()
