"""Taper un message dans Gemini, attendre la fin de la réponse et la lire."""
import logging
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote.attente import attendre_fin_reponse
from pilote.chrome import ChromeDedie
from pilote.erreurs import DelaiDepasse, PasConnecteGoogle, RepereIntrouvable, VerificationGoogle
from pilote.modeles import ResultatGemini
from pilote.selecteurs import REPERES

journal = logging.getLogger(__name__)


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


class PiloteGemini:
    def __init__(
        self,
        chrome: ChromeDedie,
        url_nouvelle: str,
        delai_reponse: float,
        stabilite: float,
        dossier_captures: Path,
    ) -> None:
        self._chrome = chrome
        self._url_nouvelle = url_nouvelle
        self._delai_reponse = delai_reponse
        self._stabilite = stabilite
        self._dossier_captures = dossier_captures

    def envoyer(self, adresse: str | None, texte: str) -> ResultatGemini:
        """Envoie `texte` dans la conversation `adresse` (None = nouvelle conversation)."""
        page = self._chrome.page()
        try:
            return self._envoyer(page, adresse, texte)
        except RepereIntrouvable as e:
            raise RepereIntrouvable(e.nom, self._capturer(page)) from e

    def est_connecte(self) -> bool:
        return not self._demande_connexion(self._chrome.page())

    def _envoyer(self, page: Page, adresse: str | None, texte: str) -> ResultatGemini:
        if adresse is None:
            page.goto(self._url_nouvelle, wait_until="domcontentloaded")
        elif page.url != adresse:
            page.goto(adresse, wait_until="domcontentloaded")
            self._attendre_historique(page)

        try:
            champ = attendre_repere(page, "champ_saisie", 15)
        except RepereIntrouvable:
            self._verifier_acces(page)
            raise
        self._verifier_acces(page)

        nb_avant = compter(page, "reponse")
        champ.first.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        # insert_text n'appuie sur aucune touche : les retours à la ligne
        # n'envoient pas le message en morceaux.
        page.keyboard.insert_text(texte)
        attendre_repere(page, "bouton_envoyer", 5).first.click()

        # Un seul délai pour tout le message : Gemini peut réfléchir longtemps
        # avant même d'afficher le début de sa réponse.
        fin = time.monotonic() + self._delai_reponse
        nouvelle = self._attendre_nouvelle_reponse(page, nb_avant, fin)
        reponse = attendre_fin_reponse(
            lire_texte=nouvelle.inner_text,
            generation_en_cours=lambda: self._generation_en_cours(page),
            delai_max=max(0.0, fin - time.monotonic()),
            stabilite=self._stabilite,
        )
        return ResultatGemini(reponse=reponse.strip(), adresse=page.url)

    def _attendre_historique(self, page: Page) -> None:
        """Après ouverture d'une conversation existante, attendre que ses
        anciennes réponses soient affichées (sinon l'une d'elles serait prise
        pour la nouvelle)."""
        attendre_repere(page, "reponse", 15)
        precedent, stable_depuis = -1, time.monotonic()
        fin = time.monotonic() + 10
        while time.monotonic() < fin:
            nombre = compter(page, "reponse")
            if nombre != precedent:
                precedent, stable_depuis = nombre, time.monotonic()
            elif time.monotonic() - stable_depuis >= 1.0:
                return
            time.sleep(0.2)

    def _attendre_nouvelle_reponse(self, page: Page, nb_avant: int, fin: float) -> Locator:
        while time.monotonic() < fin:
            reponses = premier_present(page, "reponse")
            if reponses is not None and reponses.count() > nb_avant:
                return reponses.nth(nb_avant)
            time.sleep(0.3)
        if self._generation_en_cours(page):
            raise DelaiDepasse(self._delai_reponse, "")
        raise RepereIntrouvable("reponse")

    def _generation_en_cours(self, page: Page) -> bool:
        bouton = premier_present(page, "bouton_arreter")
        return bouton is not None and bouton.first.is_visible()

    def _verifier_acces(self, page: Page) -> None:
        if "/sorry/" in page.url or "challenge" in page.url:
            raise VerificationGoogle()
        if self._demande_connexion(page):
            raise PasConnecteGoogle()

    def _demande_connexion(self, page: Page) -> bool:
        return "accounts.google.com" in page.url or premier_present(page, "lien_connexion") is not None

    def _capturer(self, page: Page) -> str | None:
        try:
            self._dossier_captures.mkdir(parents=True, exist_ok=True)
            chemin = self._dossier_captures / f"repere-{datetime.now():%Y%m%d-%H%M%S}.png"
            page.screenshot(path=str(chemin), full_page=True)
            return str(chemin)
        except ErreurPlaywright:
            journal.exception("Capture d'écran impossible")
            return None
