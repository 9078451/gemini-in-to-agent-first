"""Piloter un site de chat (ChatGPT, Claude.ai) dans le Chrome dédié, avec le compte de
l'utilisateur, comme Gemini : taper le message, attendre la réponse en la lisant au fil
de l'eau, la rendre avec son HTML.

Plus simple que le pilote de Gemini : le site garde le modèle choisi sur sa page (sauf
ChatGPT, qui en accepte un dans l'adresse d'une discussion neuve) et n'a pas de niveaux.
Les repères de chaque site sont dans `pilote/sites.py`.
"""
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote.attente import attendre_envoi, attendre_fin_reponse, attendre_nouvelle_reponse
from pilote.chrome import OngletSite
from pilote.erreurs import (
    DelaiDepasse, ErreurPilote, FournisseurIndisponible, Interrompu, LimiteSite, MessageAbandonne, PasConnecteSite,
    RepereIntrouvable,
)
from pilote.modeles import Modes, Option, ResultatGemini
from pilote.sites import ProfilSite
from pilote.sonde import Sonde

journal = logging.getLogger(__name__)

DELAI_ENVOI = 45.0  # s pour que la question apparaisse dans la conversation après l'envoi
TEXTE_PAGE = "() => document.body ? document.body.innerText : ''"


def premier(page: Page, candidats: list[str]) -> Locator | None:
    for selecteur in candidats:
        elements = page.locator(selecteur)
        if elements.count() > 0:
            return elements
    return None


def attendre(page: Page, candidats: list[str], delai: float, nom: str, site: str) -> Locator:
    fin = time.monotonic() + delai
    while True:
        elements = premier(page, candidats)
        if elements is not None:
            return elements
        if time.monotonic() >= fin:
            raise RepereIntrouvable(nom, site=site)
        time.sleep(0.25)


def limite_dans(texte: str, motifs: tuple[str, ...]) -> str | None:
    """La phrase de la page qui annonce une limite atteinte, s'il y en a une."""
    bas = texte.lower()
    for motif in motifs:
        i = bas.find(motif.lower())
        if i >= 0:
            debut = max(texte.rfind("\n", 0, i) + 1, i - 120)
            fin = texte.find("\n", i)
            return " ".join(texte[debut: fin if fin >= 0 else i + 160].split())[:200]
    return None


class PiloteSite:
    def __init__(self, onglet: OngletSite, profil: ProfilSite, delai_reponse: float, stabilite: float,
                 dossier_captures: Path) -> None:
        self._onglet = onglet
        self._profil = profil
        self._delai_reponse = delai_reponse
        self._stabilite = stabilite
        self._dossier_captures = dossier_captures
        self._sonde_reperes = {k: profil.reperes.get(k, []) for k in ("question", "reponse", "generation", "limite")}

    # ---- contrat Pilote ---------------------------------------------------

    def preparer(self) -> None:
        page = self._onglet.page()
        if not page.url.startswith(self._profil.prefixe):
            page.goto(self._profil.url_nouvelle, wait_until="domcontentloaded")
        self._verifier_acces(page)

    def ouvrir(self) -> None:
        """Montre l'onglet du site, pour s'y connecter."""
        page = self._onglet.page()
        if not page.url.startswith(self._profil.prefixe):
            page.goto(self._profil.url_nouvelle, wait_until="domcontentloaded")
        page.bring_to_front()

    def est_connecte(self) -> bool:
        page = self._onglet.page()
        return not self._sur_page_connexion(page) and premier(page, self._profil.reperes.get("connexion", [])) is None

    def lister_modes(self) -> Modes:
        return Modes([Option("Par défaut", "Celui choisi sur le site", True)], [])

    def lister_modeles(self) -> list[str]:
        return ["Par défaut"]

    def envoyer(
        self,
        adresse: str | None,
        texte: str,
        modele: str | None = None,
        niveau: str | None = None,
        delai: float | None = None,
        au_fil: Callable[[str, str], None] | None = None,
    ) -> ResultatGemini:
        page = self._onglet.page()
        try:
            return self._envoyer(page, adresse, texte, modele, delai or self._delai_reponse, au_fil)
        except RepereIntrouvable as e:
            raise RepereIntrouvable(e.nom, self._capturer(page), site=self._profil.nom) from e

    # ---- interne ----------------------------------------------------------

    def _envoyer(self, page: Page, adresse: str | None, texte: str, modele: str | None, delai: float,
                 au_fil: Callable[[str, str], None] | None) -> ResultatGemini:
        p = self._profil
        if adresse is None:
            cible = p.url_modele(modele) if modele and p.url_modele else p.url_nouvelle
            page.goto(cible, wait_until="domcontentloaded")
        elif page.url != adresse:
            page.goto(adresse, wait_until="domcontentloaded")
        self._verifier_acces(page)
        champ = attendre(page, p.reperes["champ_saisie"], 20, "champ_saisie", p.nom)
        self._verifier_acces(page)
        sonde = Sonde(page, self._sonde_reperes, html=p.html)
        if adresse is not None:
            self._attendre_historique(sonde)
        nb_avant = sonde.reponses()
        questions_avant = sonde.questions()

        champ.first.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.keyboard.insert_text(texte)
        bouton = premier(page, p.reperes["bouton_envoyer"])
        if bouton is not None:
            bouton.first.click()
        else:
            page.keyboard.press("Enter")
        try:
            attendre_envoi(sonde.questions, questions_avant, DELAI_ENVOI, sonde.limite, intervalle=0.25)
        except ErreurPilote:
            self._vider(page, champ)
            raise self._erreur_envoi(page)

        debut = time.monotonic()
        fin = debut + delai
        sonde.viser(nb_avant)
        suivi = (lambda t: au_fil(t, sonde.html())) if au_fil else None
        try:
            if not attendre_nouvelle_reponse(sonde.reponses, sonde.questions, sonde.generation, nb_avant,
                                             questions_avant + 1, delai, intervalle=0.2, au_fil=suivi):
                raise RepereIntrouvable("reponse", site=p.nom)
            reponse = attendre_fin_reponse(sonde.texte, sonde.generation, max(0.0, fin - time.monotonic()),
                                           self._stabilite, intervalle=0.25, au_fil=suivi)
        except Interrompu:
            self._arreter(page)
            raise Interrompu(sonde.texte().strip(), sonde.html(), page.url)
        except MessageAbandonne as e:
            raise FournisseurIndisponible(p.nom, "le site a abandonné le message sans répondre") from e
        except DelaiDepasse as e:
            raise FournisseurIndisponible(p.nom, f"réponse inachevée après {delai:.0f} s", e.partiel) from e
        sonde.viser(nb_avant)  # relue tout de suite : la dernière version du HTML
        return ResultatGemini(
            reponse=reponse.strip(), adresse=page.url, html=sonde.html(), modele=modele, niveau=None,
            duree=round(time.monotonic() - debut, 1),
        )

    def _attendre_historique(self, sonde: Sonde) -> None:
        """Conversation rouverte : attendre que ses anciennes réponses soient affichées (sinon
        l'une d'elles serait prise pour la nouvelle)."""
        precedent, stable_depuis = -1, time.monotonic()
        fin = time.monotonic() + 10
        while time.monotonic() < fin:
            nombre = sonde.reponses()
            if nombre != precedent:
                precedent, stable_depuis = nombre, time.monotonic()
            elif nombre > 0 and time.monotonic() - stable_depuis >= 1.0:
                return
            time.sleep(0.2)

    def _verifier_acces(self, page: Page) -> None:
        if self._sur_page_connexion(page):
            raise PasConnecteSite(self._profil.nom)

    def _sur_page_connexion(self, page: Page) -> bool:
        return any(morceau in page.url for morceau in self._profil.pages_connexion)

    def _erreur_envoi(self, page: Page) -> ErreurPilote:
        """Message non pris : une limite annoncée dans la page, sinon le site ne répond pas."""
        try:
            limite = limite_dans(page.evaluate(TEXTE_PAGE), self._profil.textes_limite)
        except ErreurPlaywright:
            limite = None
        if limite:
            return LimiteSite(self._profil.nom, limite)
        if self._sur_page_connexion(page):
            return PasConnecteSite(self._profil.nom)
        return FournisseurIndisponible(self._profil.nom, "le site n'a pas pris le message (connexion ? vérification ?)")

    def _vider(self, page: Page, champ: Locator) -> None:
        """Sinon le site pourrait envoyer ce message plus tard, tout seul."""
        try:
            champ.first.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
        except ErreurPlaywright:
            pass

    def _arreter(self, page: Page) -> None:
        try:
            for selecteur in self._profil.reperes["generation"]:
                if not selecteur.startswith("button"):
                    continue  # une marque d'écriture, pas un bouton
                bouton = page.locator(selecteur)
                if bouton.count() and bouton.first.is_visible():
                    bouton.first.click(timeout=3000)
                    return
        except ErreurPlaywright:
            journal.warning("Bouton « Arrêter » introuvable sur %s", self._profil.nom, exc_info=True)

    def _capturer(self, page: Page) -> str | None:
        try:
            self._dossier_captures.mkdir(parents=True, exist_ok=True)
            chemin = self._dossier_captures / f"repere-{self._profil.id}-{datetime.now():%Y%m%d-%H%M%S}.png"
            page.screenshot(path=str(chemin), full_page=True)
            return str(chemin)
        except ErreurPlaywright:
            journal.exception("Capture d'écran impossible")
            return None
