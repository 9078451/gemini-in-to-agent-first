"""Le cadre envoyé à Gemini avec chaque demande de l'utilisateur en mode Cowork.

Gemini web n'est pas fait pour piloter un PC : sans rappel, il redevient un chat
qui conseille au lieu d'agir. Chaque demande part donc avec son rôle, les actions
(tirées du catalogue), la marche à suivre, l'état du dossier et la demande elle-même,
bien délimitée. En anglais : Gemini suit ces consignes plus précisément ; il parle
français à l'utilisateur.
"""
from pathlib import Path

from cowork.catalogue import liste_compacte

DOSSIERS_IGNORES = {".git", "node_modules", "__pycache__", ".venv", "venv"}
_COMPTE_MAX = 10000  # au-delà, on ne compte plus le reste d'un très gros dossier

_GABARIT = """[AGENT FIRST · COWORK]
You are the Cowork agent of Agent First, running on the user's Windows PC.
You do the work yourself by sending actions; Agent First executes them and sends back the results. \
Never tell the user to run something: run it yourself.

HOW TO ANSWER
- Your messages contain ONLY JSON actions: one ```json block with an action object or a list of actions. \
Up to {max_actions} per message, run in order, stopping at the first error.
- Write to the user in French inside the actions (plan steps, questions, summary).
- JSON strings: escape " as \\", new lines as \\n, backslashes as \\\\.

ACTIONS
{actions}

WORKFLOW
1. Plan first: restate the request as concrete steps with "plan".
2. Look before changing: list, read or search what you will touch.
3. Work in batches: every round trip with Agent First is slow, so put in ONE message every action \
you can already decide, e.g. create + start + visit + plan with [x] + done. The batch stops at the first error, \
so a done at the end only counts if everything before it succeeded. Stop a batch only where you need a result \
you have not seen yet (read a file before editing it, look at an error before fixing it).
4. Verify: run the code or the tests; for a server, start it then visit it, in the same batch. Fix what fails.
5. Finish with "done" only when every step is [x] and verified: Agent First refuses it otherwise. \
If the request is unclear, use "ask".

SAFETY
File actions only work inside the working folder. Deletions and risky commands need the user's approval; \
Agent First asks for it. If refused, find another way.

WORKING FOLDER: {dossier}   (all paths are relative to it)
FOLDER CONTENT ({entrees}):
{contenu}
RUNNING PROCESSES: {processus}
LAST TASK: {derniere_tache}

{entete}
\"\"\"
{demande}
\"\"\"
Reply now with your first actions. If the request is simple, do it all in this first message."""


def cadre(
    dossier: Path,
    demande: str,
    *,
    contenu: str,
    entrees: str,
    processus: str,
    derniere_tache: str,
    reponse: bool,
    max_actions: int,
) -> str:
    return _GABARIT.format(
        max_actions=max_actions,
        actions=liste_compacte(),
        dossier=dossier,
        contenu=contenu,
        entrees=f"{entrees} {'entry' if entrees == '1' else 'entries'}",
        processus=processus or "none",
        derniere_tache=derniere_tache or "none",
        entete="USER ANSWER TO YOUR QUESTION:" if reponse else "USER REQUEST:",
        demande=demande,
    )


def arborescence(dossier: Path, max_entrees: int) -> tuple[str, str]:
    """Le contenu du dossier, dossiers d'abord, indenté ; coupé à `max_entrees` lignes.
    Avec le nombre d'entrées (« 10150+ » quand le compte s'est arrêté)."""
    lignes, reste = [], 0
    for ligne in _entrees(dossier, 0):
        if len(lignes) < max_entrees:
            lignes.append(ligne)
        else:
            reste += 1
            if reste >= _COMPTE_MAX:
                break
    if not lignes:
        return "(empty)", "0"
    plus = "+" if reste >= _COMPTE_MAX else ""
    entrees = f"{len(lignes) + reste}{plus}"
    if reste:
        lignes.append(f"… ({reste}{plus} more)")
    return "\n".join(lignes), entrees


def _entrees(dossier: Path, profondeur: int):
    try:
        enfants = sorted(dossier.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return
    retrait = "  " * profondeur
    for enfant in enfants:
        if not enfant.is_dir():
            yield retrait + enfant.name
        elif enfant.name not in DOSSIERS_IGNORES:
            yield f"{retrait}{enfant.name}/"
            if not enfant.is_symlink():  # pas de boucle sans fin sur un lien vers un parent
                yield from _entrees(enfant, profondeur + 1)
