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
}
