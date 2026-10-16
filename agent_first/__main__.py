"""Lance Agent First : python -m agent_first [--ouvrir]"""
import argparse
import logging
import threading

import uvicorn

import config
from agent_first.cowork_service import ServiceCowork
from agent_first.dossier import choisir_dossier
from agent_first.fenetre import ouvrir_quand_pret, repond
from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from agent_first.serveur import creer_app
from cowork.actions import Executeur
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
    def fabrique_executeur(dossier):
        return Executeur(dossier, config.DELAI_COMMANDE, config.TAILLE_MAX_SORTIE)

    cowork = ServiceCowork(
        file, historique, fabrique_executeur,
        config.MAX_ETAPES_COWORK, config.ECHECS_FORMAT_MAX, config.TAILLE_MAX_SORTIE,
    )
    app = creer_app(
        file, historique, config.DELAI_AGENT, chrome.est_lance, par_defaut,
        config.DOSSIER_WEB, cowork=cowork, choisir_dossier=choisir_dossier,
    )
    if args.ouvrir:
        url = f"http://{config.HOTE_AGENT}:{config.PORT_AGENT}/"
        threading.Thread(
            target=ouvrir_quand_pret, args=(config.CHEMIN_CHROME, url, lambda: repond(url)), daemon=True
        ).start()
    try:
        uvicorn.run(app, host=config.HOTE_AGENT, port=config.PORT_AGENT)
    finally:
        file.arreter()


if __name__ == "__main__":
    main()
