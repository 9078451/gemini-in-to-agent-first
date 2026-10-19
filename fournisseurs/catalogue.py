"""Les fournisseurs connus d'Agent First et ce qu'il faut savoir de chacun."""
from dataclasses import dataclass

WEB = "web"  # site piloté dans le Chrome dédié, avec le compte de l'utilisateur
API = "api"  # API par clé, appelée directement


@dataclass(frozen=True)
class Fournisseur:
    id: str
    nom: str
    type: str
    base_url: str = ""
    cle_requise: bool = True
    # Accepte un niveau de réflexion (Min. / Moyen / Max.).
    niveaux: bool = False
    # Proposés tant que la liste n'a pas été lue chez le fournisseur.
    modeles_suggeres: tuple[str, ...] = ()
    # Où trouver la clé, ou quoi faire pour s'en servir.
    aide: str = ""
    # Site : sa page d'accueil (nouvelle conversation) et le début de ses adresses.
    url_site: str = ""
    prefixe_site: str = ""
    # API : accepte `reasoning_effort` (format OpenAI) ; retiré pour un modèle qui le refuse.
    effort_openai: bool = False


CATALOGUE: dict[str, Fournisseur] = {
    f.id: f
    for f in (
        Fournisseur(
            "gemini", "Gemini", WEB, cle_requise=False, niveaux=True,
            url_site="https://gemini.google.com/app", prefixe_site="https://gemini.google.com",
            aide="Ton compte Google, dans le Chrome dédié.",
        ),
        Fournisseur(
            "chatgpt", "ChatGPT", WEB, cle_requise=False,
            url_site="https://chatgpt.com/", prefixe_site="https://chatgpt.com",
            aide="Ton compte ChatGPT, dans le Chrome dédié.",
        ),
        Fournisseur(
            "claude_web", "Claude.ai", WEB, cle_requise=False,
            url_site="https://claude.ai/new", prefixe_site="https://claude.ai",
            aide="Ton compte Claude, dans le Chrome dédié.",
        ),
        Fournisseur(
            "anthropic", "Claude", API, base_url="https://api.anthropic.com", niveaux=True,
            modeles_suggeres=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
            aide="Clé sur platform.claude.com → API keys.",
        ),
        Fournisseur(
            "openai", "OpenAI", API, base_url="https://api.openai.com/v1", niveaux=True, effort_openai=True,
            aide="Clé sur platform.openai.com → API keys.",
        ),
        Fournisseur(
            "google", "Gemini API", API, base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            niveaux=True, effort_openai=True,
            aide="Clé gratuite sur aistudio.google.com → Get API key.",
        ),
        Fournisseur(
            "mistral", "Mistral", API, base_url="https://api.mistral.ai/v1",
            aide="Clé sur console.mistral.ai → API keys.",
        ),
        Fournisseur(
            "groq", "Groq", API, base_url="https://api.groq.com/openai/v1",
            aide="Clé gratuite sur console.groq.com → API keys. Très rapide.",
        ),
        Fournisseur(
            "openrouter", "OpenRouter", API, base_url="https://openrouter.ai/api/v1",
            aide="Clé sur openrouter.ai → Keys. Des centaines de modèles, dont des gratuits.",
        ),
        Fournisseur(
            "deepseek", "DeepSeek", API, base_url="https://api.deepseek.com/v1",
            aide="Clé sur platform.deepseek.com → API keys.",
        ),
        Fournisseur(
            "xai", "xAI (Grok)", API, base_url="https://api.x.ai/v1",
            aide="Clé sur console.x.ai → API keys.",
        ),
        Fournisseur(
            "ollama", "Ollama", API, base_url="http://127.0.0.1:11434/v1", cle_requise=False,
            aide="Gratuit, sur ce PC, sans Internet : installe Ollama (ollama.com), puis « ollama pull llama3.2 ».",
        ),
        Fournisseur(
            "perso", "Compatible OpenAI", API, base_url="http://127.0.0.1:1234/v1", cle_requise=False,
            aide="Tout serveur au format OpenAI (LM Studio, vLLM…) : indique son adresse.",
        ),
    )
}

# Toujours actif : c'est le fournisseur d'origine d'Agent First.
PAR_DEFAUT = "gemini"
# Site sans choix de modèle par Agent First : il garde le sien.
MODELE_SITE = "Par défaut"


def fournisseur(identifiant: str) -> Fournisseur | None:
    return CATALOGUE.get(identifiant)
