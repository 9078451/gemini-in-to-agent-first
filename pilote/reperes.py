"""Trouver les repères d'une page (candidats de `selecteurs.REPERES` pour Gemini, ou du
profil d'un autre site : `sites.Site.reperes`)."""
import time

from playwright.sync_api import Locator, Page

from pilote.erreurs import RepereIntrouvable
from pilote.selecteurs import REPERES


def premier_present(page: Page, nom: str, reperes: dict[str, list[str]] | None = None) -> Locator | None:
    """Premier candidat du repère `nom` qui trouve au moins un élément."""
    for selecteur in (REPERES if reperes is None else reperes).get(nom, []):
        elements = page.locator(selecteur)
        if elements.count() > 0:
            return elements
    return None


def attendre_repere(page: Page, nom: str, delai: float, reperes: dict[str, list[str]] | None = None) -> Locator:
    fin = time.monotonic() + delai
    while True:
        elements = premier_present(page, nom, reperes)
        if elements is not None:
            return elements
        if time.monotonic() >= fin:
            raise RepereIntrouvable(nom)
        time.sleep(0.3)


def compter(page: Page, nom: str, reperes: dict[str, list[str]] | None = None) -> int:
    elements = premier_present(page, nom, reperes)
    return elements.count() if elements is not None else 0
