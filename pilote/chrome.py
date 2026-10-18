"""Lancer le Chrome dédié et s'y brancher avec Playwright.

`ChromeDedie` est partagé par tous les fils (`est_lance`, `lancer`). Chaque fil
qui pilote Gemini a son `OngletGemini` : sa connexion Playwright et son onglet,
utilisés uniquement depuis ce fil (Playwright synchrone l'exige).
"""
import json
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright.sync_api import Error as ErreurPlaywright

from pilote.erreurs import ChromeInjoignable

ONGLET_COWORK = "cowork"
ONGLET_CHAT = "chat"
GEMINI = "https://gemini.google.com"
# Chaque onglet piloté porte le nom de son rôle dans son sessionStorage (propre à l'onglet,
# gardé quand il change de page) : Agent First le retrouve après un redémarrage.
CLE_ONGLET = "agent-first-onglet"
LIRE_MARQUE = "cle => sessionStorage.getItem(cle)"
ECRIRE_MARQUE = "([cle, role]) => sessionStorage.setItem(cle, role)"
# Une fenêtre cachée derrière d'autres (l'app, l'éditeur…) continue d'écrire la réponse.
DRAPEAUX_SANS_VEILLE = [
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]


class ChromeDedie:
    def __init__(self, chemin_chrome: Path, dossier_profil: Path, port: int, url_accueil: str) -> None:
        self._chemin_chrome = chemin_chrome
        self._dossier_profil = dossier_profil
        self.port = port
        self.url_accueil = url_accueil
        self._verrou_lancement = threading.Lock()
        # Choisir et marquer un onglet se fait sous ce verrou : un fil ne prend jamais
        # l'onglet qu'un autre vient d'ouvrir et n'a pas encore marqué.
        self.verrou_onglets = threading.Lock()

    def commande_lancement(self) -> list[str]:
        return [
            str(self._chemin_chrome),
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self._dossier_profil}",
            "--no-first-run",
            "--no-default-browser-check",
            *DRAPEAUX_SANS_VEILLE,
            self.url_accueil,
        ]

    def est_lance(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as reponse:
                json.load(reponse)
            return True
        except (OSError, ValueError):
            return False

    def lancer(self, delai: float = 15.0) -> None:
        """Lance Chrome s'il ne l'est pas. Deux fils qui le demandent en même temps
        n'en ouvrent qu'un : le second attend le premier."""
        with self._verrou_lancement:
            if self.est_lance():
                return
            self._dossier_profil.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(self.commande_lancement())
            fin = time.monotonic() + delai
            while time.monotonic() < fin:
                if self.est_lance():
                    return
                time.sleep(0.3)
        raise ChromeInjoignable()


def choisir_onglet(
    onglets: list[tuple[str, str | None]], role: str, principal: bool, prefixe: str = GEMINI,
) -> int | None:
    """Parmi les onglets (adresse, marque), celui à piloter pour `role`, ou None pour en
    ouvrir un. L'onglet marqué pour ce rôle d'abord ; le principal prend sinon un onglet
    non marqué du site (`prefixe` : celui ouvert au lancement de Chrome pour Gemini). Jamais
    celui d'un autre rôle."""
    gemini = [(i, marque) for i, (adresse, marque) in enumerate(onglets) if adresse.startswith(prefixe)]
    for i, marque in gemini:
        if marque == role:
            return i
    if principal:
        for i, marque in gemini:
            if marque is None:
                return i
    return None


class OngletGemini:
    """L'onglet d'un fil, sur Gemini ou un autre site (`prefixe`, ouvert sur `url`).
    `principal` : adopte l'onglet du site déjà ouvert ; les autres ouvrent leur propre
    fenêtre (dans la même fenêtre, l'onglet de derrière bute : menu des modèles fermé,
    texte figé, vu en essai réel)."""

    def __init__(
        self, chrome: ChromeDedie, role: str, principal: bool = False, prefixe: str = GEMINI, url: str | None = None,
    ) -> None:
        self._chrome = chrome
        self._role = role
        self._principal = principal
        self._prefixe = prefixe
        self._url = url
        self._playwright: Playwright | None = None
        self._navigateur: Browser | None = None
        self._page: Page | None = None

    def page(self) -> Page:
        """L'onglet de ce fil. Lance Chrome et s'y branche si besoin (par exemple si
        l'utilisateur l'a fermé entre deux messages) ; rouvre l'onglet s'il a été fermé."""
        navigateur = self._brancher()
        if self._page is not None and not self._page.is_closed():
            return self._page
        with self._chrome.verrou_onglets:
            contexte = navigateur.contexts[0]
            onglets = list(contexte.pages)
            i = choisir_onglet([(o.url, _marque(o, self._prefixe)) for o in onglets], self._role, self._principal,
                               self._prefixe)
            page = onglets[i] if i is not None else self._ouvrir_fenetre(navigateur)
            page.evaluate(ECRIRE_MARQUE, [CLE_ONGLET, self._role])
        self._page = page
        return page

    def fermer(self) -> None:
        """Débranche Playwright. Le Chrome dédié et l'onglet restent ouverts."""
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._navigateur = None
        self._page = None

    def _brancher(self) -> Browser:
        if self._navigateur is None or not self._navigateur.is_connected():
            self._page = None
            if not self._chrome.est_lance():
                self._chrome.lancer()
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            try:
                self._navigateur = self._playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self._chrome.port}")
            except ErreurPlaywright as e:
                raise ChromeInjoignable() from e
        return self._navigateur

    def _ouvrir_fenetre(self, navigateur: Browser) -> Page:
        contexte = navigateur.contexts[0]
        session = navigateur.new_browser_cdp_session()
        try:
            with contexte.expect_page() as nouvelle:
                session.send("Target.createTarget", {"url": self._url or self._chrome.url_accueil, "newWindow": True})
        finally:
            session.detach()
        page = nouvelle.value
        page.wait_for_load_state("domcontentloaded")
        return page


def _marque(onglet: Page, prefixe: str = GEMINI) -> str | None:
    """Le rôle marqué dans cet onglet du site, ou None (non marqué, illisible, autre site)."""
    if not onglet.url.startswith(prefixe):
        return None
    try:
        return onglet.evaluate(LIRE_MARQUE, CLE_ONGLET)
    except ErreurPlaywright:
        return None
