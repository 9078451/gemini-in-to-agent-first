import socket
from pathlib import Path

from pilote.chrome import ChromeDedie


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def nouveau_chrome(port: int = 9222) -> ChromeDedie:
    return ChromeDedie(Path("C:/chrome.exe"), Path("C:/profil"), port, "https://gemini.google.com/app")


def test_commande_utilise_le_profil_dedie_et_le_port():
    commande = nouveau_chrome(9333).commande_lancement()
    assert commande[0] == str(Path("C:/chrome.exe"))
    assert "--remote-debugging-port=9333" in commande
    assert f"--user-data-dir={Path('C:/profil')}" in commande
    assert commande[-1] == "https://gemini.google.com/app"


def test_commande_n_ouvre_pas_le_port_sur_le_reseau():
    commande = nouveau_chrome().commande_lancement()
    assert not any(a.startswith("--remote-debugging-address") for a in commande)


def test_est_lance_faux_si_personne_n_ecoute():
    assert nouveau_chrome(port_libre()).est_lance() is False
