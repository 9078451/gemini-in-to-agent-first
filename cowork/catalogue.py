"""Le catalogue des actions que Gemini peut demander : la source unique du protocole.

Chaque action est décrite une fois (nom anglais, champs, aide, exemple, ancien nom
français). Le mode d'emploi envoyé à Gemini, la lecture du JSON, la validation des
champs et l'aiguillage de l'exécuteur en découlent : rien ne peut diverger.
"""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    nom: str
    champs: dict


@dataclass(frozen=True)
class Definition:
    nom: str
    requis: tuple[str, ...]
    optionnels: tuple[str, ...]
    aide: str
    exemple: dict
    ancien_nom: str | None = None


_DEFINITIONS = [
    Definition("list", (), ("path",), "list a folder (default: the working folder)",
               {"action": "list", "path": "."}, "lister"),
    Definition("read", ("path",), (), "read a text file",
               {"action": "read", "path": "app.py"}, "lire"),
    Definition("search", ("pattern",), ("glob",), "find a text in files (glob filters the files)",
               {"action": "search", "pattern": "def main", "glob": "**/*.py"}, "chercher"),
    Definition("create", ("path", "content"), (), "create or overwrite a file (missing folders are created)",
               {"action": "create", "path": "app.py", "content": "print(\"hi\")\n"}, "creer"),
    Definition("edit", ("path", "old", "new"), (), "replace a passage that appears exactly once in the file",
               {"action": "edit", "path": "app.py", "old": "\"hi\"", "new": "\"hello\""}, "modifier"),
    Definition("delete", ("path",), (), "delete a file or folder (the user is asked first)",
               {"action": "delete", "path": "old.txt"}, "supprimer"),
    Definition("run", ("command",), (), "run a PowerShell command that finishes, get its output",
               {"action": "run", "command": "python app.py"}, "commande"),
    Definition("start", ("command",), (), "start a long-running command in the background (server, watcher)",
               {"action": "start", "command": "python server.py"}),
    Definition("logs", ("id",), (), "new output of a started process",
               {"action": "logs", "id": "1"}),
    Definition("stop", ("id",), (), "stop a started process",
               {"action": "stop", "id": "1"}),
    Definition("visit", ("url",), ("method", "body"), "HTTP request to a local server (localhost only)",
               {"action": "visit", "url": "http://localhost:8000/"}),
    Definition("plan", ("steps",), (), "set or update your plan, steps in French with [ ] or [x]",
               {"action": "plan", "steps": ["[x] Lire le code", "[ ] Corriger le bug"]}),
    Definition("ask", ("question",), (), "ask the user a question (in French) and wait for the answer",
               {"action": "ask", "question": "Quel port utiliser ?"}),
    Definition("done", ("summary",), (), "finish the task with a short summary in French",
               {"action": "done", "summary": "J'ai corrigé le bug et vérifié que le serveur répond."}),
]

CATALOGUE: dict[str, Definition] = {d.nom: d for d in _DEFINITIONS}
ANCIENS_NOMS: dict[str, str] = {d.ancien_nom: d.nom for d in _DEFINITIONS if d.ancien_nom}
ALIAS_CHAMPS: dict[str, str] = {
    "chemin": "path", "contenu": "content", "avant": "old", "apres": "new", "texte": "command", "motif": "pattern",
}
# Toutes les clés connues : elles servent de bornes pour relire un JSON abîmé.
CLES: tuple[str, ...] = tuple(dict.fromkeys(
    ["action", *(c for d in _DEFINITIONS for c in d.requis + d.optionnels), *ALIAS_CHAMPS]
))
# Le champ montré à côté du nom de l'action dans un résultat (« create index.html »).
_PRINCIPAL = {"list": "path", "read": "path", "create": "path", "edit": "path", "delete": "path", "visit": "url"}
_ENTRE_GUILLEMETS = {"run": "command", "start": "command", "search": "pattern"}


def normaliser(objet: dict) -> Action | None:
    """Objet JSON de Gemini → Action aux noms anglais. None sans clé « action » texte."""
    nom = objet.get("action")
    if not isinstance(nom, str) or not nom.strip():
        return None
    nom = nom.strip().lower()
    champs = {}
    for cle, valeur in objet.items():
        if cle == "action":
            continue
        cle = ALIAS_CHAMPS.get(cle, cle)
        champs[cle] = valeur if cle == "steps" and isinstance(valeur, list) else _texte(valeur)
    return Action(ANCIENS_NOMS.get(nom, nom), champs)


def _texte(valeur) -> str:
    if isinstance(valeur, str):
        return valeur
    if valeur is None:
        return ""
    if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        return str(valeur)
    # Objet ou liste (un package.json écrit comme objet…) : remis en JSON lisible.
    return json.dumps(valeur, indent=2, ensure_ascii=False)


def valider(action: Action) -> str | None:
    definition = CATALOGUE.get(action.nom)
    if definition is None:
        return f'unknown action "{action.nom}" (known: {", ".join(CATALOGUE)})'
    for champ in definition.requis:
        if action.champs.get(champ) is None:
            return f'missing field "{champ}"'
    return None


def resume_action(action: Action) -> str:
    c = action.champs
    if action.nom in _PRINCIPAL:
        return f"{action.nom} {c.get(_PRINCIPAL[action.nom]) or '.'}"
    if action.nom in _ENTRE_GUILLEMETS:
        return f'{action.nom} "{c.get(_ENTRE_GUILLEMETS[action.nom], "")}"'
    if action.nom in ("logs", "stop"):
        return f"{action.nom} #{str(c.get('id', '')).lstrip('#')}"
    return action.nom


def liste_compacte() -> str:
    return "\n".join(f"- {json.dumps(d.exemple, ensure_ascii=False)} : {d.aide}" for d in _DEFINITIONS)
