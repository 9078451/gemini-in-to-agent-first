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
    """Premier bloc json valide contenant une clé « action ». None sinon."""
    for correspondance in _BLOC.finditer(message):
        try:
            objet = json.loads(correspondance.group(1))
        except ValueError:
            continue
        if isinstance(objet, dict) and isinstance(objet.get("action"), str):
            champs = {k: str(v) for k, v in objet.items() if k != "action"}
            return Action(nom=objet["action"], champs=champs)
    return None


def est_termine(message: str) -> bool:
    """Vrai si le message annonce la fin (aucune action et le mot TERMINÉ)."""
    return lire_action(message) is None and "TERMINÉ" in message


def formater_resultat(ok: bool, corps: str) -> str:
    return f"OK\n{corps}" if ok else f"ERREUR : {corps}"
