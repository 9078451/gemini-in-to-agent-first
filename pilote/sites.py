"""Les sites d'assistants pilotés dans le Chrome dédié : Gemini, ChatGPT, Claude, Le Chat
(Mistral), DeepSeek, Grok. Même principe partout (taper, envoyer, attendre la fin, lire) :
seul le profil change — adresses, repères de la page, ce que le site sait créer.

Gemini a été vérifié en essai réel. Pour les autres, les repères viennent de leur page
publique et sont à vérifier sur ton compte : `python -m pilote.inspecter --site chatgpt`.
Quand un site change sa page, c'est ici (ou dans `selecteurs.py` pour Gemini) qu'on corrige.
"""
import re
from dataclasses import dataclass, field

from pilote import selecteurs as g

# Messages d'un site saturé, ou d'un compte à court de messages ou de crédits : la demande
# peut passer à un autre assistant (redondance). Seulement des formules nettes : une réponse
# ordinaire peut parler de « réessayer plus tard » sans que le site soit saturé.
LIMITE = re.compile(
    r"(?:you(?:'ve| have)|vous avez|tu as) (?:reached|hit|atteint)[^.!?\n]{0,40}limit"
    r"|usage limit|message limit|limite d'utilisation|limite de messages|limite quotidienne"
    r"|out of (?:free )?(?:messages|credits)|(?:n'avez|n'as) plus de (?:messages|crédits)|crédits? (?:épuisés|insuffisants)"
    r"|(?:unexpectedly |very )?high demand|forte demande|at capacity|overloaded|surchargé|capacity constraints",
    re.IGNORECASE,
)
MENU = "[role='menu'] [role='menuitem'], [role='menuitemradio'], [role='menu'] [role='menuitemcheckbox'], [role='listbox'] [role='option']"
EN_COURS = "[role='progressbar'], [class*='loading' i], [class*='spinner' i], [aria-busy='true']"
DECOR = "button, svg, [role='button'], [class*='copy' i], [class*='sr-only'], .sticky"
LIGNES_DECOR = ("Copier le code", "Copy code", "Copier", "Copy", "Copié !", "Copied!", "Modifier", "Edit", "Exécuter", "Run")


@dataclass(frozen=True)
class Site:
    nom: str  # identifiant : « gemini », « chatgpt »…
    libelle: str  # nom affiché : « Gemini », « ChatGPT »…
    compte: str  # le compte où se connecter : « Google », « OpenAI »…
    url: str  # nouvelle discussion
    prefixe: str  # toutes les pages du site commencent par là
    reperes: dict[str, list[str]]
    contenu: str  # blocs de texte de la réponse (HTML gardé, et texte si `texte_par_contenu`)
    conteneur: str  # bloc de toute la réponse (médias)
    texte_par_contenu: bool = True  # le texte est lu dans les blocs `contenu` (sinon tout le bloc de réponse)
    code: str = "pre"  # bloc de code (Gemini : code-block, avec son entête)
    entete_code: str = ""
    decor: str = DECOR  # retiré du HTML de la réponse
    lignes_decor: tuple[str, ...] = LIGNES_DECOR  # lignes de boutons retirées du texte
    hors_medias: str = "button svg, [class*='avatar' i], [class*='favicon' i], [class*='source' i]"
    media_en_cours: str = EN_COURS
    zone_saisie: str = "form"  # autour du champ de saisie (aperçus des fichiers joints)
    pieces_saisie: str = "img, [class*='file' i], [class*='attachment' i], [data-testid*='file' i], [data-testid*='attachment' i]"
    televersement: str = EN_COURS
    options_outil: tuple[str, ...] = (MENU,)
    options_modele: str = MENU
    outils: tuple[str, ...] = ()  # médias que le site sait créer : « image », « video », « musique »
    modes: str = "menu"  # « gemini » : sélecteur de mode et niveaux ; « menu » : une liste de modèles
    connexion_url: tuple[str, ...] = ()  # pages de connexion
    verification_url: tuple[str, ...] = ()  # pages de vérification (« êtes-vous un humain ? »)
    limite: re.Pattern = field(default=LIMITE)


GEMINI = Site(
    nom="gemini", libelle="Gemini", compte="Google",
    url="https://gemini.google.com/app", prefixe="https://gemini.google.com",
    reperes=g.REPERES, contenu=g.CONTENU_REPONSE, conteneur=g.CONTENEUR_REPONSE,
    texte_par_contenu=False, code=g.BLOC_CODE, entete_code=g.ENTETE_CODE, decor=g.DECOR_REPONSE, lignes_decor=(),
    hors_medias=g.HORS_MEDIAS, media_en_cours=g.MEDIA_EN_COURS, zone_saisie="",
    pieces_saisie=g.PIECES_SAISIE, televersement=g.TELEVERSEMENT_EN_COURS, options_outil=tuple(g.OPTIONS_OUTIL),
    outils=("image", "video", "musique"), modes="gemini",
    connexion_url=("accounts.google.com",), verification_url=("/sorry/", "challenge"),
)

_VERIFICATION = ["iframe[src*='challenges.cloudflare.com']", "#challenge-form", "#cf-challenge-running"]

CHATGPT = Site(
    nom="chatgpt", libelle="ChatGPT", compte="OpenAI (ChatGPT)",
    url="https://chatgpt.com/", prefixe="https://chatgpt.com",
    reperes={
        "champ_saisie": ["#prompt-textarea[contenteditable='true']", "div#prompt-textarea", "textarea#prompt-textarea"],
        "bouton_envoyer": ["button[data-testid='send-button']", "#composer-submit-button",
                           "button[aria-label*='Envoyer' i]", "button[aria-label*='Send' i]"],
        "bouton_arreter": ["button[data-testid='stop-button']", "button[aria-label*='Arrêter' i]",
                           "button[aria-label*='Stop' i]"],
        "question": ["[data-message-author-role='user']"],
        "reponse": ["article:has([data-message-author-role='assistant'])", "[data-message-author-role='assistant']"],
        "lien_connexion": ["button[data-testid='login-button']", "a[href*='/auth/login']"],
        "verification": _VERIFICATION,
        "bandeau_limite": ["[data-testid*='rate-limit' i]", "[class*='rate-limit' i]"],
        "bouton_mode": ["button[data-testid='model-switcher-dropdown-button']", "button[aria-label*='Sélecteur de modèle' i]",
                        "button[aria-label*='model selector' i]"],
        "bouton_importer": ["button[data-testid='composer-plus-btn']", "button[aria-label*='Ajouter des fichiers' i]",
                            "button[aria-label*='Add files' i]", "button[aria-label*='Joindre' i]"],
        "bouton_outils": ["button[data-testid='composer-plus-btn']", "button[aria-label*='Outils' i]",
                          "button[aria-label*='Tools' i]"],
    },
    contenu=".markdown", conteneur="article",
    options_modele="[data-testid^='model-switcher-'][role], " + MENU,
    outils=("image",), connexion_url=("/auth/login", "auth.openai.com"),
)

CLAUDE = Site(
    nom="claude", libelle="Claude", compte="Anthropic (Claude)",
    url="https://claude.ai/new", prefixe="https://claude.ai",
    reperes={
        "champ_saisie": ["div[contenteditable='true'].ProseMirror", "[data-testid='chat-input'] [contenteditable='true']",
                         "div[contenteditable='true'][aria-label]"],
        "bouton_envoyer": ["button[aria-label='Envoyer le message']", "button[aria-label*='Send message' i]",
                           "button[aria-label*='Envoyer' i]", "button[aria-label*='Send' i]"],
        "bouton_arreter": ["button[aria-label*='Arrêter' i]", "button[aria-label*='Stop' i]",
                           "div[data-is-streaming='true']"],
        "question": ["[data-testid='user-message']", ".font-user-message"],
        "reponse": ["div[data-is-streaming]", ".font-claude-response", ".font-claude-message"],
        "lien_connexion": ["a[href='/login']", "a[href*='/login?']", "button[data-testid='login-button']"],
        "verification": _VERIFICATION,
        "bandeau_limite": ["[data-testid*='limit' i]", "[class*='usage-limit' i]"],
        "bouton_mode": ["button[data-testid='model-selector-dropdown']", "button[aria-label*='modèle' i][aria-haspopup]",
                        "button[aria-label*='model' i][aria-haspopup]"],
        "bouton_importer": ["button[data-testid='input-menu-plus']", "button[aria-label*='Ajouter des fichiers' i]",
                            "button[aria-label*='Add files' i]", "button[aria-label*='Joindre' i]",
                            "button[aria-label*='Attach' i]"],
    },
    contenu=".font-claude-response, .font-claude-message, .standard-markdown", conteneur="div[data-is-streaming]",
    zone_saisie="fieldset", connexion_url=("/login",),
)

MISTRAL = Site(
    nom="mistral", libelle="Le Chat", compte="Mistral",
    url="https://chat.mistral.ai/chat", prefixe="https://chat.mistral.ai",
    reperes={
        "champ_saisie": ["textarea[name='message.text']", "div[contenteditable='true'].ProseMirror", "form textarea"],
        "bouton_envoyer": ["button[type='submit'][aria-label*='Envoyer' i]", "button[aria-label*='Send' i]",
                           "form button[type='submit']"],
        "bouton_arreter": ["button[aria-label*='Arrêter' i]", "button[aria-label*='Stop' i]"],
        "question": ["[data-message-author-role='user']", "[class*='user-message' i]"],
        "reponse": ["[data-message-author-role='assistant']", "[class*='assistant-message' i]"],
        "lien_connexion": ["a[href*='/login']", "a[href*='auth.mistral.ai']"],
        "verification": _VERIFICATION,
        "bouton_mode": ["button[aria-label*='modèle' i]", "button[aria-label*='model' i]"],
        "bouton_importer": ["button[aria-label*='Joindre' i]", "button[aria-label*='Attach' i]",
                            "button[aria-label*='Ajouter' i]"],
        "bouton_outils": ["button[aria-label*='Outils' i]", "button[aria-label*='Tools' i]"],
    },
    contenu="[class*='markdown' i], .prose", conteneur="[data-message-author-role='assistant']",
    outils=("image",), connexion_url=("auth.mistral.ai", "/login"),
)

DEEPSEEK = Site(
    nom="deepseek", libelle="DeepSeek", compte="DeepSeek",
    url="https://chat.deepseek.com/", prefixe="https://chat.deepseek.com",
    reperes={
        "champ_saisie": ["textarea#chat-input", "textarea[placeholder]"],
        "bouton_envoyer": ["div[role='button'][aria-disabled='false']:has(svg)", "button[aria-label*='Send' i]",
                           "button[aria-label*='Envoyer' i]"],
        "bouton_arreter": ["div[role='button']:has(rect)", "button[aria-label*='Stop' i]"],
        "question": ["div.ds-message:not(:has(.ds-markdown))", "[class*='user-message' i]"],
        "reponse": ["div.ds-message:has(.ds-markdown)", ".ds-markdown"],
        "lien_connexion": ["a[href*='/sign_in']", "input[type='password']"],
        "verification": _VERIFICATION,
        "bouton_importer": ["div[role='button']:has(input[type='file'])", "button[aria-label*='Upload' i]"],
    },
    contenu=".ds-markdown", conteneur="div.ds-message", zone_saisie="",
    connexion_url=("/sign_in",),
)

GROK = Site(
    nom="grok", libelle="Grok", compte="X (Grok)",
    url="https://grok.com/", prefixe="https://grok.com",
    reperes={
        "champ_saisie": ["textarea[aria-label*='Grok' i]", "div[contenteditable='true'].ProseMirror", "form textarea"],
        "bouton_envoyer": ["button[type='submit'][aria-label*='Soumettre' i]", "button[aria-label*='Submit' i]",
                           "form button[type='submit']"],
        "bouton_arreter": ["button[aria-label*='Arrêter' i]", "button[aria-label*='Stop' i]"],
        "question": ["div.items-end .message-bubble", "[data-testid='user-message']"],
        "reponse": ["div.items-start .message-bubble", "[data-testid='assistant-message']"],
        "lien_connexion": ["a[href*='/sign-in']", "a[href*='accounts.x.ai']"],
        "verification": _VERIFICATION,
        "bouton_mode": ["button[aria-label*='Sélecteur de modèle' i]", "button[aria-label*='Model select' i]"],
        "bouton_importer": ["button[aria-label*='Joindre' i]", "button[aria-label*='Attach' i]"],
    },
    contenu=".response-content-markdown, [class*='markdown' i], .prose", conteneur=".message-bubble",
    outils=("image",), connexion_url=("accounts.x.ai", "/sign-in"),
)

SITES: dict[str, Site] = {s.nom: s for s in (GEMINI, CHATGPT, CLAUDE, MISTRAL, DEEPSEEK, GROK)}
