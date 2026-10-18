"""Lire et choisir le modèle d'un site dont le sélecteur est une simple liste (ChatGPT,
Claude…) : un bouton ouvre un menu, une option par modèle (nom, puis description).

Pas de niveau de réflexion séparé : ces sites le rangent dans le nom du modèle
(« Thinking », « Extended »…).
"""
import re
import time

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as DelaiPlaywright

from pilote.erreurs import ErreurPilote, ModeleIntrouvable
from pilote.modeles import Modes, Option
from pilote.reperes import attendre_repere, premier_present

LIRE = """(elements) => elements
  .filter((e) => (e.checkVisibility ? e.checkVisibility() : !!e.offsetParent))
  .map((e) => {
    const lignes = e.innerText.split('\\n').map((l) => l.trim()).filter(Boolean);
    const actif = ['aria-checked', 'aria-selected', 'aria-current'].some((a) => e.getAttribute(a) === 'true')
      || e.getAttribute('data-state') === 'checked'
      || !!e.querySelector("[data-state='checked'], [data-testid*='check' i], svg[class*='check' i]");
    const sous_menu = e.getAttribute('aria-haspopup') === 'menu' || e.hasAttribute('aria-expanded');
    return {nom: lignes[0] || '', description: lignes.slice(1).join(' '), actif, sous_menu};
  })"""


def norme(nom: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", nom.lower())


def rang_de(noms: list[str], voulu: str) -> int | None:
    """L'option qui correspond à `voulu` : même nom (aux espaces près), sinon la seule qui
    contient tous ses mots (« Sonnet » → « Claude Sonnet 4.5 »)."""
    cible = norme(voulu)
    for i, nom in enumerate(noms):
        if norme(nom) == cible:
            return i
    mots = [norme(m) for m in voulu.split() if norme(m)]
    candidats = [i for i, nom in enumerate(noms) if mots and all(m in norme(nom) for m in mots)]
    return candidats[0] if len(candidats) == 1 else None


def lire_modes(page: Page, site) -> Modes:
    """Les modèles proposés ; Modes([], []) si le site n'a pas de sélecteur visible."""
    bouton = premier_present(page, "bouton_mode", site.reperes)
    if bouton is None or not bouton.first.is_visible():
        return Modes([], [])
    _ouvrir(page, bouton.first, site)
    try:
        options = [o for o in _lire(page, site) if o["nom"] and not o["sous_menu"]]
    finally:
        _fermer(page, site)
    if options and not any(o["actif"] for o in options):
        # Pas de coche lisible : le bouton affiche en général le modèle en cours.
        libelle = norme(bouton.first.inner_text())
        for o in options:
            o["actif"] = bool(libelle) and norme(o["nom"]) in libelle
    return Modes([Option(o["nom"], o["description"], o["actif"]) for o in options], [])


def choisir_modele(page: Page, nom: str, site) -> None:
    bouton = attendre_repere(page, "bouton_mode", 10, site.reperes).first
    _ouvrir(page, bouton, site)
    try:
        options = page.locator(site.options_modele).filter(visible=True)
        noms = [(options.nth(i).inner_text().split("\n") or [""])[0].strip() for i in range(options.count())]
        i = rang_de(noms, nom)
        if i is None:
            raise ModeleIntrouvable(nom)
        options.nth(i).click(timeout=5000)
    finally:
        _fermer(page, site)


def choisir_niveau(page: Page, nom: str, site) -> bool:
    return False  # pas de niveau séparé


def _ouvrir(page: Page, bouton, site, delai: float = 6.0) -> None:
    fin = time.monotonic() + delai
    while True:
        bouton.click(timeout=5000)
        try:
            page.locator(site.options_modele).filter(visible=True).first.wait_for(state="visible", timeout=2000)
            return
        except DelaiPlaywright as e:
            if time.monotonic() >= fin:
                raise ErreurPilote(f"Le menu des modèles de {site.libelle} ne s'ouvre pas : renvoie ton message.") from e


def _lire(page: Page, site) -> list[dict]:
    return page.locator(site.options_modele).evaluate_all(LIRE)


def _fermer(page: Page, site) -> None:
    if page.locator(site.options_modele).filter(visible=True).count():
        page.keyboard.press("Escape")
        time.sleep(0.2)
