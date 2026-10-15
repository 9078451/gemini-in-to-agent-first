"""Trouver les repères de la page Gemini (candidats de `selecteurs.REPERES`)."""
import time

from playwright.sync_api import Locator, Page

from pilote.erreurs import RepereIntrouvable
from pilote.selecteurs import REPERES


def premier_present(page: Page, nom: str) -> Locator | None:
    """Premier candidat du repère `nom` qui trouve au moins un élément."""
    for selecteur in REPERES[nom]:
        elements = page.locator(selecteur)
        if elements.count() > 0:
            return elements
    return None


def attendre_repere(page: Page, nom: str, delai: float) -> Locator:
    fin = time.monotonic() + delai
    while True:
        elements = premier_present(page, nom)
        if elements is not None:
            return elements
        if time.monotonic() >= fin:
            raise RepereIntrouvable(nom)
        time.sleep(0.3)


def compter(page: Page, nom: str) -> int:
    elements = premier_present(page, nom)
    return elements.count() if elements is not None else 0
