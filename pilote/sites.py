"""Les sites de chat pilotés comme Gemini : leurs adresses et leurs repères.

Chaque repère a plusieurs candidats CSS, essayés dans l'ordre (le premier qui trouve
quelque chose sert). Quand un site change sa page, c'est ici qu'on corrige — vérifier
avec `python -m pilote.inspecter --site chatgpt` (ou `claude_web`).

Relevé le 19/10/2026 sur chatgpt.com (sans compte) : champ `textarea#mobile-composer-prompt`,
bouton « Envoyer un message ». Les repères des messages viennent des versions connues des
deux sites (attributs `data-message-author-role`, `data-testid`, `data-is-streaming`).
"""
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote


@dataclass(frozen=True)
class ProfilSite:
    id: str
    nom: str
    url_nouvelle: str
    prefixe: str
    reperes: dict[str, list[str]]
    # Extraction du HTML d'une réponse (voir pilote/sonde.py).
    html: dict[str, str] | None = None
    # Adresse d'une discussion neuve avec ce modèle, si le site le permet.
    url_modele: Callable[[str], str] | None = None
    # Morceaux d'adresse d'une page de connexion : le compte n'est pas connecté.
    pages_connexion: tuple[str, ...] = ()
    # Le site s'utilise sans compte (moins de modèles, limites plus basses).
    sans_compte: bool = False
    # Textes d'un refus pour limite atteinte (cherchés dans la page en cas d'échec).
    textes_limite: tuple[str, ...] = field(default_factory=tuple)


CHATGPT = ProfilSite(
    id="chatgpt",
    nom="ChatGPT",
    url_nouvelle="https://chatgpt.com/",
    prefixe="https://chatgpt.com",
    reperes={
        "champ_saisie": [
            "#prompt-textarea",
            "textarea#mobile-composer-prompt",
            "div[contenteditable='true'].ProseMirror",
            "textarea[aria-label*='ChatGPT']",
            "div[contenteditable='true']",
        ],
        "bouton_envoyer": [
            "button[data-testid='send-button']",
            "#composer-submit-button",
            "button[aria-label='Envoyer un message']",
            "button[aria-label*='Envoyer']",
            "button[aria-label*='Send']",
        ],
        "question": [
            "[data-message-author-role='user']",
            "[data-testid='user-message']",
        ],
        "reponse": [
            "[data-message-author-role='assistant']",
            "[data-testid='assistant-message']",
        ],
        "generation": [
            "button[data-testid='stop-button']",
            "button[aria-label*='Arrêter']",
            "button[aria-label*='Stop']",
        ],
        "limite": [],
        "connexion": [
            "button[data-testid='login-button']",
        ],
    },
    html={"contenu": ".markdown, .prose", "code": "pre", "entete": ".__aucun__", "decor": "button, svg", "texte_contenu": True},
    url_modele=lambda modele: f"https://chatgpt.com/?model={quote(modele)}",
    pages_connexion=("auth.openai.com", "/auth/login"),
    sans_compte=True,
    textes_limite=("reached our limit", "atteint la limite", "limite de messages", "usage cap", "Too many requests"),
)

CLAUDE_WEB = ProfilSite(
    id="claude_web",
    nom="Claude.ai",
    url_nouvelle="https://claude.ai/new",
    prefixe="https://claude.ai",
    reperes={
        "champ_saisie": [
            "div[contenteditable='true'].ProseMirror",
            "[data-testid='chat-input'] div[contenteditable='true']",
            "div[contenteditable='true']",
            "textarea",
        ],
        "bouton_envoyer": [
            "button[aria-label='Send message']",
            "button[aria-label*='Envoyer']",
            "button[aria-label*='Send']",
        ],
        "question": [
            "[data-testid='user-message']",
            "[data-message-author-role='user']",
        ],
        "reponse": [
            ".font-claude-response",
            "[data-is-streaming]",
            "[data-message-author-role='assistant']",
        ],
        "generation": [
            "[data-is-streaming='true']",
            "button[aria-label='Stop response']",
            "button[aria-label*='Arrêter']",
            "button[aria-label*='Stop']",
        ],
        "limite": [],
        "connexion": [],
    },
    html={"contenu": ".standard-markdown, .progressive-markdown, .prose, .markdown", "code": "pre",
          "entete": ".__aucun__", "decor": "button, svg", "texte_contenu": True},
    pages_connexion=("/login", "/onboarding", "/magic-link"),
    textes_limite=("out of free messages", "message limit", "limite de messages", "plus de messages", "usage limit"),
)

PROFILS: dict[str, ProfilSite] = {p.id: p for p in (CHATGPT, CLAUDE_WEB)}
