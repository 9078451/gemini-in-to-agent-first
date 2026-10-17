"""Cocher un outil de création de Gemini (images, vidéos, musique) avant d'envoyer.

Au mieux : si le menu « Outils » ou l'outil est introuvable (interface changée, outil
absent du compte), la demande part quand même, rédigée pour que Gemini crée le média.
"""
import logging
import re

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote.reperes import premier_present
from pilote.selecteurs import OPTIONS_OUTIL

journal = logging.getLogger(__name__)

MOTIFS = {
    "image": re.compile(r"\bimages?\b", re.IGNORECASE),
    "video": re.compile(r"\bvid[ée]os?\b|\bveo\b", re.IGNORECASE),
    "musique": re.compile(r"\bmusiques?\b|\bmusic\b|\blyria\b|\bchansons?\b|\bsongs?\b", re.IGNORECASE),
}
COCHE = "e => ['aria-checked', 'aria-pressed', 'aria-selected'].some(a => e.getAttribute(a) === 'true')"


def option_pour(libelles: list[str], outil: str) -> int | None:
    """Le rang de l'option du menu qui correspond à `outil`, ou None."""
    motif = MOTIFS[outil]
    return next((i for i, libelle in enumerate(libelles) if motif.search(" ".join(libelle.split()))), None)


def choisir_outil(page: Page, outil: str) -> bool:
    """Coche l'outil dans le menu « Outils ». True s'il est coché."""
    bouton = premier_present(page, "bouton_outils")
    if bouton is None or not bouton.first.is_visible():
        return False
    try:
        bouton.first.click(timeout=5000)
        options = _options(page)
        if options is None:
            return False
        i = option_pour([options.nth(n).inner_text() for n in range(options.count())], outil)
        if i is None:
            return False
        option = options.nth(i)
        if not option.evaluate(COCHE):  # cliquer un outil déjà coché le décocherait
            option.click(timeout=5000)
        return True
    except ErreurPlaywright:
        journal.warning("Outil « %s » non coché", outil, exc_info=True)
        return False
    finally:
        _fermer_menu(page)


def _options(page: Page) -> Locator | None:
    for _ in range(10):  # le menu s'ouvre avec une petite animation
        for selecteur in OPTIONS_OUTIL:
            options = page.locator(selecteur).filter(visible=True)
            if options.count() > 0:
                return options
        page.wait_for_timeout(200)
    return None


def _fermer_menu(page: Page) -> None:
    """Le menu se referme en général tout seul après le choix ; sinon Échap, sans vider la saisie."""
    try:
        if any(page.locator(s).filter(visible=True).count() for s in OPTIONS_OUTIL):
            page.keyboard.press("Escape")
    except ErreurPlaywright:
        pass
