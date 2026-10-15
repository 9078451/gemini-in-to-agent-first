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
