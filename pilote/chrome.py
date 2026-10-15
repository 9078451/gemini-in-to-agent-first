"""Lancer le Chrome dédié et s'y brancher avec Playwright.

`est_lance` peut être appelé depuis n'importe quel fil ; `page` et `fermer`
uniquement depuis le fil qui utilise Playwright.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright.sync_api import Error as ErreurPlaywright

from pilote.erreurs import ChromeInjoignable


class ChromeDedie:
    def __init__(self, chemin_chrome: Path, dossier_profil: Path, port: int, url_accueil: str) -> None:
        self._chemin_chrome = chemin_chrome
        self._dossier_profil = dossier_profil
        self._port = port
        self._url_accueil = url_accueil
        self._playwright: Playwright | None = None
        self._navigateur: Browser | None = None

    def commande_lancement(self) -> list[str]:
        return [
            str(self._chemin_chrome),
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._dossier_profil}",
            "--no-first-run",
            "--no-default-browser-check",
            self._url_accueil,
        ]

    def est_lance(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/json/version", timeout=1) as reponse:
                json.load(reponse)
            return True
        except (OSError, ValueError):
            return False

    def lancer(self, delai: float = 15.0) -> None:
        self._dossier_profil.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(self.commande_lancement())
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.est_lance():
                return
            time.sleep(0.3)
        raise ChromeInjoignable()

    def page(self) -> Page:
        """Onglet Gemini du Chrome dédié. Lance Chrome et s'y branche si besoin
        (par exemple si l'utilisateur l'a fermé entre deux messages)."""
        if self._navigateur is None or not self._navigateur.is_connected():
            if not self.est_lance():
                self.lancer()
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            try:
                self._navigateur = self._playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{self._port}"
                )
            except ErreurPlaywright as e:
                raise ChromeInjoignable() from e
        contexte = self._navigateur.contexts[0]
        for onglet in contexte.pages:
            if onglet.url.startswith("https://gemini.google.com"):
                return onglet
        onglet = contexte.new_page()
        onglet.goto(self._url_accueil, wait_until="domcontentloaded")
        return onglet

    def fermer(self) -> None:
        """Débranche Playwright. Le Chrome dédié reste ouvert."""
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._navigateur = None
