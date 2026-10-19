"""Fabriquer le pilote de chaque fournisseur (sauf Gemini, fabriqué par `__main__`).

`fabriques[fournisseur](role)` est appelée dans le fil de la file du fournisseur : pour un
site, c'est là que Playwright doit vivre.
"""
from typing import Callable

from fournisseurs.api_anthropic import PiloteClaudeAPI
from fournisseurs.api_openai import PiloteOpenAI
from fournisseurs.catalogue import API, CATALOGUE
from fournisseurs.memoire import MemoireFils
from fournisseurs.reglages import ReglagesFournisseurs
from pilote.modeles import Pilote


def fabriques_api(reglages: ReglagesFournisseurs, memoire: MemoireFils) -> dict[str, Callable[[str], Pilote]]:
    fabriques: dict[str, Callable[[str], Pilote]] = {"anthropic": lambda _role: PiloteClaudeAPI(reglages, memoire)}
    for identifiant, f in CATALOGUE.items():
        if f.type == API and identifiant not in fabriques:
            fabriques[identifiant] = lambda _role, i=identifiant: PiloteOpenAI(i, reglages, memoire)
    return fabriques


def ids_api() -> set[str]:
    return {i for i, f in CATALOGUE.items() if f.type == API}
