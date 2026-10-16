"""Ouvrir l'app dans une fenêtre d'application Chrome (sans onglets ni barre d'adresse).

C'est le Chrome habituel de l'utilisateur qui l'affiche, pas le Chrome dédié à Gemini.
"""
import logging
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Callable

journal = logging.getLogger(__name__)


def commande_fenetre(chemin_chrome: Path, url: str) -> list[str]:
    return [str(chemin_chrome), f"--app={url}", "--window-size=1280,820"]


def repond(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except OSError:
        return False


def ouvrir_quand_pret(
    chemin_chrome: Path,
    url: str,
    est_pret: Callable[[], bool],
    lancer: Callable[[list[str]], object] = subprocess.Popen,
    delai: float = 30.0,
    intervalle: float = 0.3,
) -> bool:
    """Attend que le serveur réponde, puis ouvre la fenêtre d'app."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if est_pret():
            lancer(commande_fenetre(chemin_chrome, url))
            return True
        time.sleep(intervalle)
    journal.warning("Agent First ne répond pas : fenêtre de l'app non ouverte")
    return False
