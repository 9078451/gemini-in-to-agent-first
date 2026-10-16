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
    return None


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


def est_termine(message: str) -> bool:
    """Vrai si le message annonce la fin (aucune action et le mot TERMINÉ)."""
    return lire_action(message) is None and "TERMINÉ" in message


def formater_resultat(ok: bool, corps: str) -> str:
    return f"OK\n{corps}" if ok else f"ERREUR : {corps}"
