"""Réglages communs : chemins, ports et délais."""
from pathlib import Path

RACINE = Path(__file__).resolve().parent

CHEMIN_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DOSSIER_PROFIL = RACINE / "profil-chrome-gemini"
PORT_CHROME = 9222
URL_GEMINI = "https://gemini.google.com/app"

HOTE_AGENT = "127.0.0.1"
PORT_AGENT = 8765
DOSSIER_WEB = RACINE / "agent_first" / "web"

DELAI_REPONSE = 180.0  # secondes max pour qu'une réponse Gemini se termine
STABILITE = 2.0  # secondes sans changement du texte = réponse finie
DELAI_AGENT = 290.0  # attente max d'Agent First (file d'attente + Gemini)

DOSSIER_DONNEES = RACINE / "donnees"
DOSSIER_JOURNAUX = RACINE / "journaux"
FICHIER_HISTORIQUE = DOSSIER_DONNEES / "historique.db"

# Utilisés tant que la liste n'a pas pu être lue dans Gemini (relevés le 2026-10-15).
MODELES_PAR_DEFAUT = [
    ("3.5 Flash-Lite", "Réponses les plus rapides"),
    ("3.8 Flash", "Aide polyvalente"),
    ("3.1 Pro", "Raisonnement avancé"),
    ("4 Argon", "Tâches complexes"),
]
NIVEAUX_PAR_DEFAUT = [("Min.", "Rapide et efficace"), ("Moyen", "Équilibré"), ("Max.", "Très poussé")]
# Présélectionnés dans l'app tant que la liste n'a pas été lue dans Gemini.
MODELE_ACTIF_PAR_DEFAUT = "4 Argon"
NIVEAU_ACTIF_PAR_DEFAUT = "Min."
