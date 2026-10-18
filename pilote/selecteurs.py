"""Tous les repères de la page Gemini, au même endroit.

Chaque repère a plusieurs candidats CSS, essayés dans l'ordre : le premier qui
trouve au moins un élément est utilisé. Quand Google change son site, c'est
ici qu'on corrige — vérifier avec `python -m pilote.inspecter`.
"""

REPERES: dict[str, list[str]] = {
    "champ_saisie": [
        "rich-textarea div.ql-editor[contenteditable='true']",
        "div[role='textbox'][contenteditable='true']",
    ],
    "bouton_envoyer": [
        "button[aria-label='Envoyer un message']",
        "button[aria-label*='Envoyer']",
        "button[aria-label*='Send']",
    ],
    "bouton_arreter": [
        "button[aria-label='Interrompre la réponse']",
        "button[aria-label*='Interrompre']",
        "button[aria-label*='Stop']",
    ],
    "question": [
        "user-query",
    ],
    # « Votre limite sera réinitialisée à … » au-dessus du champ, quand le compte a tout utilisé.
    "bandeau_limite": [
        ".inline-upgrade-banner-text",
    ],
    "reponse": [
        "model-response message-content",
        "model-response",
    ],
    "lien_connexion": [
        "a[href*='accounts.google.com/ServiceLogin']",
        "a[href*='accounts.google.com/v3/signin']",
    ],
    "bouton_mode": [
        "button[aria-label*='sélecteur de mode']",
        "button[aria-label*='mode picker']",
    ],
    # Bouton « + » de la zone de saisie : ouvre le menu d'import de fichiers.
    "bouton_importer": [
        "button[aria-label*='importation' i]",
        "button[aria-label*='Importer' i]",
        "button[aria-label*='upload' i]",
        "button[aria-label*='Ajouter des fichiers' i]",
        "uploader button",
    ],
    # Menu « Outils » de la zone de saisie : créer des images, des vidéos (Veo), de la musique…
    "bouton_outils": [
        "button[aria-label='Outils']",
        "button[aria-label*='Outils']",
        "button[aria-label*='Tools']",
        "toolbox-drawer button",
    ],
}

# Sélecteur de mode : menu des modèles et sous-menu « Niveau de réflexion ».
OPTION_MENU = "gem-menu-item[role='menuitem']"
OPTION_MODELE = "gem-menu-item[data-mode-id]"
LIBELLE_OPTION = ".label"
SOUS_LIBELLE_OPTION = ".sublabel"
ENTREE_NIVEAU = "Niveau de réflexion"

# Réponse en HTML : contenu utile, blocs de code et décor de Gemini à retirer.
CONTENU_REPONSE = ".markdown"
BLOC_CODE = "code-block"
ENTETE_CODE = ".code-block-decoration"
DECOR_REPONSE = "button, gem-icon-button, gem-icon, mat-icon, gem-popover, .table-footer, .code-block-decoration"

# Outils proposés par le menu « Outils » (le premier candidat qui trouve des éléments visibles).
OPTIONS_OUTIL = [
    "toolbox-drawer-item button",
    "[role='menuitemcheckbox']",
    "mat-action-list button",
    "[role='menu'] [role='menuitem']",
]

# Médias d'une réponse : cherchés dans tout le bloc de la réponse (le texte est dans
# message-content, une image ou une vidéo créée peut être à côté).
CONTENEUR_REPONSE = "model-response"
# Hors médias : avatar de Gemini, icônes, logos des sources citées, aperçus des liens.
HORS_MEDIAS = "bard-avatar, gem-icon, mat-icon, button[aria-label*='source' i], sources-list, source-footnote, .source-chip"
# Un média encore en préparation (image en cours de création, vidéo Veo qui se génère…).
MEDIA_EN_COURS = (
    "[role='progressbar'], mat-progress-spinner, mat-spinner, mat-progress-bar, "
    "[class*='image-loading'], [class*='video-loading'], [class*='generating'], [class*='loading-placeholder']"
)

# Pièces jointes dans la zone de saisie (aperçus des fichiers joints, hors du texte tapé).
PIECES_SAISIE = (
    "uploader-file-preview, file-preview, [data-test-id*='file-preview' i], [class*='file-preview' i], "
    "[class*='attachment' i], [class*='uploaded' i], img"
)
# Un fichier joint encore en cours d'envoi à Google.
TELEVERSEMENT_EN_COURS = "[role='progressbar'], mat-progress-spinner, mat-spinner, mat-progress-bar, [class*='loading' i]"
# Entrée du menu d'import qui ouvre le sélecteur de fichiers de l'ordinateur.
ENTREE_IMPORTER = r"import|upload|fichiers?\b|files?\b"
