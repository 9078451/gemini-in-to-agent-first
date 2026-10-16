"""Lire les actions que Gemini demande, et former les résultats qu'on lui renvoie.

Gemini écrit ses actions en JSON : un ou plusieurs blocs ```json, chacun avec un
objet action ou une liste d'actions. Gemini web affiche souvent ces blocs sans
leurs ``` (« JSON » puis l'objet) : on balaie alors le texte. Agent First répond
par un bloc « RESULTS » qui donne le sort de chaque action du lot.
"""
import json
import re
from dataclasses import dataclass

from cowork.catalogue import CLES, Action, liste_compacte, normaliser, resume_action

__all__ = ["Action", "LigneResultat", "PIED", "lire_actions", "formater_resultats", "rappel_pour", "est_erreur_gemini"]

_BLOC = re.compile(r"```json\s*(.*?)\s*```", re.S)
_DEBUT_JSON = re.compile(r"[\[{]")
COUPE = "\n…(cut)"
PIED = (
    'Reply with JSON actions only. Finish with {"action": "done", "summary": "…"} '
    "once every plan step is [x] and verified."
)


@dataclass(frozen=True)
class LigneResultat:
    rang: int
    action: Action
    statut: str  # « OK », « ERROR », « ERROR (exit code N) » ou « SKIPPED »
    corps: str


def lire_actions(message: str) -> list[Action]:
    """Toutes les actions du message, dans l'ordre. [] si aucune."""
    actions = [a for bloc in _BLOC.finditer(message) for a in _depuis_texte_json(bloc.group(1))]
    if actions:
        return actions
    actions = _balayer(message)
    if actions:
        return actions
    reparee = _reparer(message)
    if reparee:
        return [reparee]
    if "TERMINÉ" in message:  # ancien format de fin, sans JSON
        return [Action("done", {"summary": message.split("TERMINÉ", 1)[1].lstrip(" :\n").strip()})]
    return []


def _depuis_texte_json(texte: str) -> list[Action]:
    try:
        return _depuis_objet(json.loads(texte))
    except ValueError:
        return []


def _depuis_objet(objet) -> list[Action]:
    elements = objet if isinstance(objet, list) else [objet]
    actions = (normaliser(e) for e in elements if isinstance(e, dict))
    return [a for a in actions if a is not None]


def _balayer(message: str) -> list[Action]:
    """Chaque objet ou liste JSON du texte ; on reprend la lecture après sa fin,
    pour ne jamais relire les accolades d'un contenu de fichier."""
    decodeur = json.JSONDecoder()
    actions, position = [], 0
    while (debut := _DEBUT_JSON.search(message, position)) is not None:
        try:
            objet, fin = decodeur.raw_decode(message, debut.start())
        except ValueError:
            position = debut.start() + 1
            continue
        actions += _depuis_objet(objet)
        position = fin
    return actions


_CLE = re.compile(r'(?:^|[{,])\s*"(%s)"\s*:\s*"' % "|".join(CLES))
_FIN_VALEUR = re.compile(r'"\s*,\s*$')
_FIN_OBJET = re.compile(r'"\s*}\s*$')
_ECHAPPEMENTS = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}


def _reparer(message: str) -> Action | None:
    """Gemini oublie parfois d'échapper les guillemets dans les textes
    (« "old": "TCPServer(("", PORT))" ») : le JSON est invalide. On relit
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
    return normaliser(champs)


def _desechapper(texte: str) -> str:
    """\\n, \\" , \\\\… redeviennent les vrais caractères ; un \\ isolé reste tel quel."""
    return re.sub(r"\\(.)", lambda m: _ECHAPPEMENTS.get(m.group(1), m.group(0)), texte, flags=re.S)


def _couper(texte: str, taille_max: int) -> str:
    return texte if len(texte) <= taille_max else texte[:taille_max] + COUPE


def formater_resultats(lignes: list[LigneResultat], taille_max: int, taille_max_message: int, note: str = "") -> str:
    blocs = []
    for ligne in lignes:
        entete = f"[{ligne.rang}] {resume_action(ligne.action)}: {ligne.statut}"
        corps = _couper(ligne.corps, taille_max)
        blocs.append(f"{entete}\n{corps}" if corps else entete)
    texte = _couper("RESULTS\n" + "\n".join(blocs), taille_max_message)
    if note:
        texte += f"\n{note}"
    return f"{texte}\n---\n{PIED}"


RAPPEL_JSON = (
    "Your JSON is invalid. Inside strings, write \\\" for a quote, \\n for a new line and \\\\ for a backslash. "
    "Send the same actions again, fixed, in one ```json block."
)


def rappel_pour(message: str) -> str:
    """Le rappel à envoyer après une réponse illisible : précis si Gemini a
    tenté une action (JSON abîmé), complet sinon."""
    if '"action"' in message:
        return RAPPEL_JSON
    return (
        "Format not understood. Your messages must contain ONLY JSON actions in one ```json block "
        "(an action object or a list of actions). Do the work yourself with actions; "
        'finish with {"action": "done", "summary": "…"}.\n'
        f"ACTIONS\n{liste_compacte()}"
    )


# Messages que Gemini affiche quand LUI a un problème (pas une faute de format).
_ERREUR_GEMINI = re.compile(
    r"something went wrong|try your request again|un problème est survenu|"
    r"une erreur s'est produite|réessayez plus tard",
    re.I,
)


def est_erreur_gemini(message: str) -> bool:
    """Réponse vide, ou message d'erreur de Gemini lui-même (« Sorry, something went wrong »)."""
    texte = message.replace("Gemini a dit", "", 1).strip()
    if not texte:
        return True
    return len(texte) < 300 and not lire_actions(message) and bool(_ERREUR_GEMINI.search(texte))
