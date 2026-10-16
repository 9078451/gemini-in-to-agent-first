"""Lire les actions que Gemini demande, et former les résultats qu'on lui renvoie.

Gemini demande une action en écrivant un unique bloc ```json contenant un objet
avec une clé « action ». Agent First l'exécute et renvoie un bloc « OK … » ou
« ERREUR : … ».
"""
import json
import re
from dataclasses import dataclass

_BLOC = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


@dataclass(frozen=True)
class Action:
    nom: str
    champs: dict[str, str]


def lire_action(message: str) -> Action | None:
    """Premier bloc json valide contenant une clé « action ». None sinon.

    Gemini web affiche le bloc de code sans ses ``` (« JSON » puis l'objet) : à
    défaut de bloc balisé, on prend le premier objet JSON du texte qui a une clé
    « action ».
    """
    for correspondance in _BLOC.finditer(message):
        action = _vers_action(correspondance.group(1))
        if action:
            return action
    decodeur = json.JSONDecoder()
    for position, caractere in enumerate(message):
        if caractere != "{":
            continue
        try:
            objet, _fin = decodeur.raw_decode(message, position)
        except ValueError:
            continue
        action = _vers_action(objet)
        if action:
            return action
    return _reparer(message)


# Clés possibles d'une action : elles servent de bornes pour relire un JSON abîmé.
CLES = ("action", "chemin", "contenu", "avant", "apres", "texte", "motif", "glob")
_CLE = re.compile(r'(?:^|[{,])\s*"(%s)"\s*:\s*"' % "|".join(CLES))
_FIN_VALEUR = re.compile(r'"\s*,\s*$')
_FIN_OBJET = re.compile(r'"\s*}\s*$')
_ECHAPPEMENTS = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}


def _reparer(message: str) -> Action | None:
    """Gemini oublie parfois d'échapper les guillemets dans les textes
    (« "avant": "TCPServer(("", PORT))" ») : le JSON est invalide. On relit
    alors l'objet en prenant les clés connues comme bornes des valeurs."""
    debut_action = message.find('"action"')
    debut = message.rfind("{", 0, debut_action + 1) if debut_action >= 0 else -1
    fin = message.rfind("}")
    if debut < 0 or fin < debut_action:
        return None
    objet = message[debut : fin + 1]
    cles = list(_CLE.finditer(objet))
    noms = [c.group(1) for c in cles]
    if "action" not in noms or len(set(noms)) != len(noms):
        return None
    champs = {}
    for i, cle in enumerate(cles):
        suite = objet[cle.end() : cles[i + 1].start() + 1] if i + 1 < len(cles) else objet[cle.end() :]
        borne = (_FIN_VALEUR if i + 1 < len(cles) else _FIN_OBJET).search(suite)
        if borne is None:
            return None
        champs[cle.group(1)] = _desechapper(suite[: borne.start()])
    nom = champs.pop("action")
    return Action(nom=nom, champs=champs) if nom else None


def _desechapper(texte: str) -> str:
    """\\n, \\" , \\\\… redeviennent les vrais caractères ; un \\ isolé reste tel quel."""
    return re.sub(r"\\(.)", lambda m: _ECHAPPEMENTS.get(m.group(1), m.group(0)), texte, flags=re.S)


def _vers_action(source) -> Action | None:
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except ValueError:
            return None
    if isinstance(source, dict) and isinstance(source.get("action"), str):
        champs = {k: str(v) for k, v in source.items() if k != "action"}
        return Action(nom=source["action"], champs=champs)
    return None


RAPPEL_GENERAL = (
    "Format non compris. Réponds avec UNE action dans un unique bloc ```json, "
    'par exemple {"action": "lire", "chemin": "x.py"}, ou « TERMINÉ : … » quand c\'est fini.'
)
RAPPEL_JSON = (
    "Ton bloc JSON est invalide. Dans un texte entre guillemets, écris \\\" pour un guillemet, "
    "\\n pour un retour à la ligne et \\\\ pour une barre oblique inverse. "
    "Renvoie la même action, corrigée, dans un unique bloc ```json."
)

# Messages que Gemini affiche quand LUI a un problème (pas une faute de format).
_ERREUR_GEMINI = re.compile(
    r"something went wrong|try your request again|un problème est survenu|"
    r"une erreur s'est produite|réessayez plus tard",
    re.I,
)


def rappel_pour(message: str) -> str:
    """Le rappel à envoyer après une réponse illisible : précis si Gemini a
    tenté une action (JSON abîmé), général sinon."""
    return RAPPEL_JSON if '"action"' in message else RAPPEL_GENERAL


def est_erreur_gemini(message: str) -> bool:
    """Réponse vide, ou message d'erreur de Gemini lui-même (« Sorry, something went wrong »)."""
    texte = message.replace("Gemini a dit", "", 1).strip()
    if not texte:
        return True
    return len(texte) < 300 and lire_action(message) is None and bool(_ERREUR_GEMINI.search(texte))


def est_termine(message: str) -> bool:
    """Vrai si le message annonce la fin (aucune action et le mot TERMINÉ)."""
    return lire_action(message) is None and "TERMINÉ" in message


def formater_resultat(ok: bool, corps: str) -> str:
    return f"OK\n{corps}" if ok else f"ERREUR : {corps}"
