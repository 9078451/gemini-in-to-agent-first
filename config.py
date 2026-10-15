"""Réglages communs : chemins, ports et délais."""
from pathlib import Path

RACINE = Path(__file__).resolve().parent

CHEMIN_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DOSSIER_PROFIL = RACINE / "profil-chrome-gemini"
PORT_CHROME = 9222
URL_GEMINI = "https://gemini.google.com/app"

HOTE_AGENT = "127.0.0.1"
PORT_AGENT = 8765

DELAI_REPONSE = 180.0  # secondes max pour qu'une réponse Gemini se termine
STABILITE = 2.0  # secondes sans changement du texte = réponse finie
DELAI_AGENT = 290.0  # attente max d'Agent First (file d'attente + Gemini)
DELAI_GUI = 300.0  # attente max de la fenêtre

DOSSIER_DONNEES = RACINE / "donnees"
DOSSIER_JOURNAUX = RACINE / "journaux"
FICHIER_CONVERSATIONS = DOSSIER_DONNEES / "conversations.json"
