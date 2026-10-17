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
DELAI_REPONSE_COWORK = 600.0  # s, par message en Cowork : 4 Argon peut réfléchir plusieurs minutes avant d'écrire
STABILITE = 2.0  # secondes sans changement du texte = réponse finie
DELAI_AGENT = 290.0  # attente max d'Agent First (file d'attente + Gemini)

# Mode Cowork
DELAI_COMMANDE = 120.0  # secondes max pour une commande PowerShell
MAX_TOURS_COWORK = 40  # garde-fou : nombre de messages à Gemini par tâche
MAX_ACTIONS_PAR_MESSAGE = 10  # actions exécutées par message de Gemini (lot)
RELANCES_FIN_MAX = 2  # « done » refusé au plus N fois par tâche (plan inachevé, travail non vérifié)
TAILLE_MAX_SORTIE = 8000  # caractères gardés d'une sortie de commande
ECHECS_FORMAT_MAX = 3  # arrêt après N réponses de Gemini au format cassé
DELAI_ACCORD = 600.0  # s : sans réponse à une demande d'accord, la tâche Cowork s'arrête
MAX_PROCESSUS = 3  # processus en arrière-plan (start) par conversation
ATTENTE_DEMARRAGE = 3.0  # s : sortie lue après un start avant de répondre à Gemini
DELAI_VISITE = 10.0  # s : délai d'une requête « visit »
MAX_ENTREES_ARBORESCENCE = 150  # lignes du contenu du dossier envoyé à Gemini
TAILLE_MAX_MESSAGE = 30000  # caractères d'un message de résultats envoyé à Gemini
TOURS_GEMINI_MAX = 30  # messages dans une conversation Gemini avant d'en ouvrir une neuve (avec un résumé)

# API réseau (autres programmes, autres PC du réseau), protégée par une clé
API_ACTIVE = True
HOTE_API = "0.0.0.0"
PORT_API = 8766
ESSAIS_CLE_MAX = 10  # mauvaises clés tolérées par minute et par adresse, puis blocage d'une minute

DOSSIER_DONNEES = RACINE / "donnees"
DOSSIER_JOURNAUX = RACINE / "journaux"
FICHIER_HISTORIQUE = DOSSIER_DONNEES / "historique.db"
FICHIER_CLE_API = DOSSIER_DONNEES / "cle_api.txt"

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
