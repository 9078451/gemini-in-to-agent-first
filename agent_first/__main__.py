"""Lance Agent First : python -m agent_first"""
import logging

import uvicorn

import config
from agent_first.conversations import MemoireConversations
from agent_first.file_attente import FileAttente
from agent_first.serveur import creer_app
from pilote.chrome import ChromeDedie
from pilote.gemini import PiloteGemini


def main() -> None:
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
    memoire = MemoireConversations(config.FICHIER_CONVERSATIONS)
    app = creer_app(file, memoire, config.DELAI_AGENT, chrome.est_lance)
    try:
        uvicorn.run(app, host=config.HOTE_AGENT, port=config.PORT_AGENT)
    finally:
        file.arreter()


if __name__ == "__main__":
    main()
