"""Lire et régler le sélecteur de mode de Gemini : modèle et niveau de réflexion.

Usage :
  python -m pilote.modes                                  affiche modèles et niveaux
  python -m pilote.modes --modele "3.1 Pro" --niveau Max.  règle puis affiche
"""
import argparse
import re
import sys
import time

from playwright.sync_api import Locator, Page

from pilote.erreurs import ErreurPilote, ModeleIntrouvable, NiveauIntrouvable
from pilote.modeles import Modes, Option
from pilote.reperes import attendre_repere
from pilote.selecteurs import ENTREE_NIVEAU, LIBELLE_OPTION, OPTION_MENU, OPTION_MODELE, SOUS_LIBELLE_OPTION

# Gemini sépare numéro et nom par une espace insécable : les noms lus sont
# remis avec des espaces ordinaires.
LIRE_OPTIONS = """(elements, s) => elements.filter(e => e.offsetParent).map(e => ({
  nom: (e.querySelector(s.libelle) || e).innerText.replace(/\\s+/g, ' ').trim(),
  description: (e.querySelector(s.sous_libelle) || {innerText: ''}).innerText.replace(/\\s+/g, ' ').trim(),
  actif: e.classList.contains('selected'),
  modele: e.matches(s.modele),
}))"""
OPTION_NIVEAU = f"{OPTION_MENU}:not({OPTION_MODELE})"


def motif_libelle(nom: str) -> re.Pattern:
    """Libellé d'option exactement égal à `nom`, quels que soient les espaces
    (Gemini utilise des espaces insécables)."""
    return re.compile(r"^\s*" + r"\s+".join(map(re.escape, nom.split())) + r"\s*$")


def lire_modes(page: Page) -> Modes:
    """Ouvre le sélecteur, lit modèles et niveaux, referme sans rien changer."""
    _ouvrir(page)
    try:
        modeles = [Option(o["nom"], o["description"], o["actif"]) for o in _lire(page) if o["modele"]]
        niveaux = []
        if _ouvrir_niveaux(page):
            niveaux = [
                Option(o["nom"], o["description"], o["actif"])
                for o in _lire(page)
                if not o["modele"] and o["nom"] != ENTREE_NIVEAU
            ]
    finally:
        _fermer(page)
    return Modes(modeles, niveaux)


def choisir_modele(page: Page, nom: str) -> None:
    _ouvrir(page)
    try:
        option = _option(page, nom, OPTION_MODELE)
        if option.count() == 0:
            raise ModeleIntrouvable(nom)
        option.first.click()
    finally:
        _fermer(page)
    # Vérifié dans le menu (option « selected ») : le libellé du bouton varie
    # (« actuellement Argon », « actuellement Argon Max. »…).
    if lire_modes(page).modele_actif != nom:
        raise ModeleIntrouvable(nom)


def choisir_niveau(page: Page, nom: str) -> bool:
    """Règle le niveau de réflexion. False si Gemini ne propose pas de niveau."""
    _ouvrir(page)
    try:
        if not _ouvrir_niveaux(page):
            return False
        option = _option(page, nom, OPTION_NIVEAU)
        if option.count() == 0:
            raise NiveauIntrouvable(nom)
        option.first.click()
    finally:
        _fermer(page)
    if lire_modes(page).niveau_actif != nom:
        raise NiveauIntrouvable(nom)
    return True


def _ouvrir(page: Page) -> None:
    attendre_repere(page, "bouton_mode", 10).first.click()
    page.locator(OPTION_MODELE).first.wait_for(state="visible", timeout=5000)


def _fermer(page: Page) -> None:
    for _ in range(2):
        page.keyboard.press("Escape")
        time.sleep(0.3)


def _lire(page: Page) -> list[dict]:
    return page.locator(OPTION_MENU).evaluate_all(
        LIRE_OPTIONS, {"libelle": LIBELLE_OPTION, "sous_libelle": SOUS_LIBELLE_OPTION, "modele": OPTION_MODELE}
    )


def _option(page: Page, nom: str, selecteur: str) -> Locator:
    libelle = page.locator(LIBELLE_OPTION, has_text=motif_libelle(nom))
    return page.locator(selecteur).filter(has=libelle).filter(visible=True)


def _ouvrir_niveaux(page: Page) -> bool:
    entree = _option(page, ENTREE_NIVEAU, OPTION_MENU)
    if entree.count() == 0:
        return False
    entree.first.click()
    fin = time.monotonic() + 5
    while time.monotonic() < fin:
        if any(not o["modele"] and o["nom"] != ENTREE_NIVEAU for o in _lire(page)):
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    import config
    from pilote.chrome import ChromeDedie

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Lit ou règle le modèle et le niveau de réflexion de Gemini.")
    parser.add_argument("--modele")
    parser.add_argument("--niveau")
    args = parser.parse_args()

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    try:
        page = chrome.page()
        attendre_repere(page, "bouton_mode", 15)
        if args.modele:
            choisir_modele(page, args.modele)
        if args.niveau:
            choisir_niveau(page, args.niveau)
        modes = lire_modes(page)
    except ErreurPilote as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        return 1
    finally:
        chrome.fermer()
    for titre, options in (("Modèles", modes.modeles), ("Niveaux de réflexion", modes.niveaux)):
        print(titre)
        for o in options:
            print(f"  {'✓' if o.actif else ' '} {o.nom:16} {o.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
