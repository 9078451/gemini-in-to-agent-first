"""Taper un message dans Gemini, attendre la fin de la réponse et la lire."""
import logging
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote import modes
from pilote.attente import attendre_fin_reponse
from pilote.chrome import ChromeDedie
from pilote.erreurs import DelaiDepasse, PasConnecteGoogle, RepereIntrouvable, VerificationGoogle
from pilote.modeles import Modes, ResultatGemini
from pilote.reperes import attendre_repere, compter, premier_present
from pilote.selecteurs import BLOC_CODE, CONTENU_REPONSE, DECOR_REPONSE, ENTETE_CODE

journal = logging.getLogger(__name__)

EXTRAIRE_HTML = """(element, s) => {
  const copie = (element.querySelector(s.contenu) || element).cloneNode(true);
  copie.querySelectorAll(s.code).forEach(bloc => {
    const entete = bloc.querySelector(s.entete);
    const langue = entete ? entete.innerText.trim().split('\\n')[0].trim() : '';
    const pre = bloc.querySelector('pre');
    if (pre && langue) pre.setAttribute('data-langue', langue);
  });
  copie.querySelectorAll(s.decor).forEach(e => e.remove());
  return copie.innerHTML;
}"""


def reglages_a_faire(
    dernier_modele: str | None, dernier_niveau: str | None, modele: str | None, niveau: str | None
) -> tuple[bool, bool]:
    """Quoi régler dans le sélecteur avant d'envoyer. Changer de modèle peut
    changer le niveau : le niveau demandé est alors réappliqué."""
    changer_modele = modele is not None and modele != dernier_modele
    changer_niveau = niveau is not None and (niveau != dernier_niveau or changer_modele)
    return changer_modele, changer_niveau


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
        # Derniers réglages connus du sélecteur de Gemini.
        self._modele: str | None = None
        self._niveau: str | None = None

    def envoyer(
        self, adresse: str | None, texte: str, modele: str | None = None, niveau: str | None = None
    ) -> ResultatGemini:
        """Envoie `texte` dans la conversation `adresse` (None = nouvelle conversation),
        après avoir réglé le modèle et le niveau demandés."""
        page = self._chrome.page()
        try:
            return self._envoyer(page, adresse, texte, modele, niveau)
        except RepereIntrouvable as e:
            raise RepereIntrouvable(e.nom, self._capturer(page)) from e

    def est_connecte(self) -> bool:
        return not self._demande_connexion(self._chrome.page())

    def lister_modes(self) -> Modes:
        page = self._chrome.page()
        attendre_repere(page, "bouton_mode", 15)
        lus = modes.lire_modes(page)
        self._modele, self._niveau = lus.modele_actif, lus.niveau_actif
        return lus

    def _envoyer(
        self, page: Page, adresse: str | None, texte: str, modele: str | None, niveau: str | None
    ) -> ResultatGemini:
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
        self._regler(page, modele, niveau)

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
        debut = time.monotonic()
        fin = debut + self._delai_reponse
        nouvelle = self._attendre_nouvelle_reponse(page, nb_avant, fin)
        reponse = attendre_fin_reponse(
            lire_texte=nouvelle.inner_text,
            generation_en_cours=lambda: self._generation_en_cours(page),
            delai_max=max(0.0, fin - time.monotonic()),
            stabilite=self._stabilite,
        )
        return ResultatGemini(
            reponse=reponse.strip(),
            adresse=page.url,
            html=self._html(nouvelle),
            modele=self._modele,
            niveau=self._niveau,
            duree=round(time.monotonic() - debut, 1),
        )

    def _regler(self, page: Page, modele: str | None, niveau: str | None) -> None:
        changer_modele, changer_niveau = reglages_a_faire(self._modele, self._niveau, modele, niveau)
        if changer_modele:
            modes.choisir_modele(page, modele)
            self._modele = modele
        if changer_niveau:
            self._niveau = niveau if modes.choisir_niveau(page, niveau) else None

    def _html(self, reponse: Locator) -> str:
        try:
            return reponse.evaluate(
                EXTRAIRE_HTML,
                {"contenu": CONTENU_REPONSE, "code": BLOC_CODE, "entete": ENTETE_CODE, "decor": DECOR_REPONSE},
            )
        except ErreurPlaywright:
            journal.warning("HTML de la réponse illisible : seul le texte est gardé", exc_info=True)
            return ""

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
