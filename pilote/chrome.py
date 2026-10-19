"""Lancer le Chrome dédié et s'y brancher avec Playwright.

`ChromeDedie` est partagé par tous les fils (`est_lance`, `lancer`). Chaque fil
qui pilote un site (Gemini, ChatGPT, Claude.ai) a son `OngletSite` : sa connexion
Playwright et son onglet, utilisés uniquement depuis ce fil (Playwright synchrone
l'exige).
"""
import json
import logging
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright.sync_api import Error as ErreurPlaywright

from pilote.erreurs import ChromeInjoignable

journal = logging.getLogger(__name__)

ONGLET_COWORK = "cowork"
ONGLET_CHAT = "chat"
PREFIXE_GEMINI = "https://gemini.google.com"
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
# Écrit par Chrome dans le profil : le port de débogage réellement ouvert (1re ligne).
FICHIER_PORT = "DevToolsActivePort"


def port_utilisable(port: int) -> bool:
    """Faux si le port est pris, ou réservé par Windows (Hyper-V/WSL réservent des plages
    au démarrage, par exemple 9123-9222 : Chrome n'y ouvre alors pas son port)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


class ChromeDedie:
    def __init__(self, chemin_chrome: Path, dossier_profil: Path, port: int, url_accueil: str) -> None:
        self._chemin_chrome = chemin_chrome
        self._dossier_profil = dossier_profil
        self.port = port  # port préféré ; s'il est indisponible, Chrome en choisit un libre
        self._port_actuel: int | None = None
        self.url_accueil = url_accueil
        self._verrou_lancement = threading.Lock()
        # Choisir et marquer un onglet se fait sous ce verrou : un fil ne prend jamais
        # l'onglet qu'un autre vient d'ouvrir et n'a pas encore marqué.
        self.verrou_onglets = threading.Lock()

    @property
    def port_actuel(self) -> int:
        """Le port de débogage du Chrome lancé (le préféré tant qu'on ne l'a pas trouvé)."""
        return self._port_actuel or self.port

    def commande_lancement(self, port: int | None = None) -> list[str]:
        return [
            str(self._chemin_chrome),
            f"--remote-debugging-port={self.port if port is None else port}",
            f"--user-data-dir={self._dossier_profil}",
            "--no-first-run",
            "--no-default-browser-check",
            *DRAPEAUX_SANS_VEILLE,
            self.url_accueil,
        ]

    def est_lance(self) -> bool:
        """Vrai si le Chrome dédié répond : sur le dernier port connu, le port préféré, ou
        celui que Chrome a écrit dans le profil (port choisi par lui)."""
        for port in dict.fromkeys(p for p in (self._port_actuel, self.port, self._port_ecrit()) if p):
            if self._repond(port):
                self._port_actuel = port
                return True
        return False

    def lancer(self, delai: float = 15.0) -> None:
        """Lance Chrome s'il ne l'est pas. Deux fils qui le demandent en même temps
        n'en ouvrent qu'un : le second attend le premier."""
        with self._verrou_lancement:
            if self.est_lance():
                return
            self._dossier_profil.mkdir(parents=True, exist_ok=True)
            port = self.port
            if not port_utilisable(port):
                # 0 : Chrome prend un port libre et l'écrit dans le profil (FICHIER_PORT).
                journal.warning("Port %d indisponible (réservé par Windows ?) : Chrome choisit un port libre", port)
                port = 0
            try:
                (self._dossier_profil / FICHIER_PORT).unlink(missing_ok=True)  # celui d'une session finie
            except OSError:
                pass
            subprocess.Popen(self.commande_lancement(port))
            fin = time.monotonic() + delai
            while time.monotonic() < fin:
                if self.est_lance():
                    return
                time.sleep(0.3)
        raise ChromeInjoignable()

    def _port_ecrit(self) -> int | None:
        try:
            return int((self._dossier_profil / FICHIER_PORT).read_text(encoding="utf-8").splitlines()[0])
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _repond(port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as reponse:
                return "Browser" in json.load(reponse)  # c'est bien un Chrome, pas un autre programme
        except (OSError, ValueError, TypeError):
            return False


def choisir_onglet(
    onglets: list[tuple[str, str | None]], role: str, principal: bool, prefixe: str = PREFIXE_GEMINI
) -> int | None:
    """Parmi les onglets (adresse, marque), celui à piloter pour `role` sur le site `prefixe`,
    ou None pour en ouvrir un. L'onglet marqué pour ce rôle d'abord ; le principal prend
    sinon un onglet du site non marqué (celui ouvert au lancement de Chrome). Jamais celui
    d'un autre rôle."""
    du_site = [(i, marque) for i, (adresse, marque) in enumerate(onglets) if adresse.startswith(prefixe)]
    for i, marque in du_site:
        if marque == role:
            return i
    if principal:
        for i, marque in du_site:
            if marque is None:
                return i
    return None


class OngletSite:
    """L'onglet d'un site pour un fil. `principal` : adopte l'onglet du site déjà ouvert ;
    les autres ouvrent leur propre fenêtre (dans la même fenêtre, l'onglet de derrière
    bute : menu des modèles fermé, texte figé, vu en essai réel avec Gemini)."""

    def __init__(self, chrome: ChromeDedie, role: str, principal: bool = False,
                 url_accueil: str | None = None, prefixe: str = PREFIXE_GEMINI) -> None:
        self._chrome = chrome
        self._role = role
        self._principal = principal
        self._url_accueil = url_accueil or chrome.url_accueil
        self._prefixe = prefixe
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
                self._navigateur = self._playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self._chrome.port_actuel}")
            except ErreurPlaywright as e:
                raise ChromeInjoignable() from e
        return self._navigateur

    def _ouvrir_fenetre(self, navigateur: Browser) -> Page:
        contexte = navigateur.contexts[0]
        session = navigateur.new_browser_cdp_session()
        try:
            with contexte.expect_page() as nouvelle:
                session.send("Target.createTarget", {"url": self._url_accueil, "newWindow": True})
        finally:
            session.detach()
        page = nouvelle.value
        page.wait_for_load_state("domcontentloaded")
        return page


class OngletGemini(OngletSite):
    """L'onglet Gemini d'un fil (le site d'origine d'Agent First)."""


def _marque(onglet: Page, prefixe: str = PREFIXE_GEMINI) -> str | None:
    """Le rôle marqué dans cet onglet du site, ou None (non marqué, illisible, autre site)."""
    if not onglet.url.startswith(prefixe):
        return None
    try:
        return onglet.evaluate(LIRE_MARQUE, CLE_ONGLET)
    except ErreurPlaywright:
        return None
