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


def test_commande_garde_les_fenetres_cachees_actives():
    # Une fenêtre du Chrome dédié cachée derrière l'app doit continuer d'écrire la réponse.
    commande = nouveau_chrome().commande_lancement()
    for drapeau in (
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
    ):
        assert drapeau in commande


def test_deux_fils_qui_lancent_chrome_n_en_ouvrent_qu_un(tmp_path, monkeypatch):
    import threading
    import time

    from pilote import chrome as module

    lances = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda commande: lances.append(commande))
    chrome = ChromeDedie(Path("C:/chrome.exe"), tmp_path / "profil", 9222, "https://gemini.google.com/app")
    monkeypatch.setattr(chrome, "est_lance", lambda: bool(lances) and time.sleep(0.2) is None)
    depart = threading.Barrier(2)

    def lancer():
        depart.wait()
        chrome.lancer(delai=5)

    fils = [threading.Thread(target=lancer) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=10)
    assert len(lances) == 1


# ---- OngletGemini : un fil, une connexion, son onglet ----------------------

from contextlib import contextmanager  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from pilote.chrome import CLE_ONGLET, ECRIRE_MARQUE, LIRE_MARQUE, OngletGemini  # noqa: E402

GEMINI = "https://gemini.google.com/app"


class FaussePage:
    def __init__(self, url, marque=None):
        self.url = url
        self.stockage = {} if marque is None else {CLE_ONGLET: marque}
        self.fermee = False
        self.lectures = 0

    def evaluate(self, script, argument=None):
        if script == LIRE_MARQUE:
            self.lectures += 1
            return self.stockage.get(argument)
        if script == ECRIRE_MARQUE:
            self.stockage[argument[0]] = argument[1]
            return None
        raise AssertionError(f"script inattendu : {script}")

    def is_closed(self):
        return self.fermee

    def wait_for_load_state(self, *_args, **_kwargs):
        pass

    @property
    def marque(self):
        return self.stockage.get(CLE_ONGLET)


class FauxContexte:
    def __init__(self, pages):
        self.toutes = list(pages)

    @property
    def pages(self):  # comme Playwright : les onglets fermés n'y sont plus
        return [p for p in self.toutes if not p.is_closed()]

    @contextmanager
    def expect_page(self):
        attente = SimpleNamespace(value=None)
        yield attente
        attente.value = self.toutes[-1]


class FauxNavigateur:
    def __init__(self, pages):
        self.contexts = [FauxContexte(pages)]
        self.fenetres = []  # paramètres de chaque Target.createTarget

    def is_connected(self):
        return True

    def new_browser_cdp_session(self):
        navigateur = self

        class Session:
            def send(self, methode, parametres):
                assert methode == "Target.createTarget"
                navigateur.fenetres.append(parametres)
                navigateur.contexts[0].toutes.append(FaussePage(parametres["url"]))
                return {"targetId": "nouvel-onglet"}

            def detach(self):
                pass

        return Session()


class OngletBranche(OngletGemini):
    """OngletGemini branché sur un faux navigateur au lieu du vrai Chrome."""

    def __init__(self, navigateur, role, principal=False):
        super().__init__(nouveau_chrome(), role, principal=principal)
        self._faux = navigateur

    def _brancher(self):
        return self._faux


def test_cowork_prend_l_onglet_gemini_ouvert_et_le_marque():
    onglets = [FaussePage("chrome://newtab/"), FaussePage(GEMINI)]
    navigateur = FauxNavigateur(onglets)
    assert OngletBranche(navigateur, "cowork", principal=True).page() is onglets[1]
    assert onglets[1].marque == "cowork" and navigateur.fenetres == []


def test_chat_ouvre_sa_propre_fenetre():
    # Dans la même fenêtre, l'onglet de derrière bute (menu fermé, texte figé) : vu en essai réel.
    gemini = FaussePage(GEMINI)
    navigateur = FauxNavigateur([gemini])
    page = OngletBranche(navigateur, "chat").page()
    assert page is not gemini and page.marque == "chat" and gemini.marque is None
    assert navigateur.fenetres == [{"url": GEMINI, "newWindow": True}]


def test_onglets_marques_retrouves_apres_un_redemarrage():
    chat, cowork = FaussePage(GEMINI + "/a", "chat"), FaussePage(GEMINI + "/b", "cowork")
    navigateur = FauxNavigateur([chat, cowork])
    assert OngletBranche(navigateur, "cowork", principal=True).page() is cowork
    assert OngletBranche(navigateur, "chat").page() is chat
    assert navigateur.fenetres == []


def test_cowork_ne_prend_jamais_l_onglet_du_chat():
    chat = FaussePage(GEMINI, "chat")
    navigateur = FauxNavigateur([chat])
    page = OngletBranche(navigateur, "cowork", principal=True).page()
    assert page is not chat and page.marque == "cowork" and chat.marque == "chat"


def test_onglet_garde_tant_qu_il_reste_ouvert():
    gemini = FaussePage(GEMINI)
    navigateur = FauxNavigateur([gemini])
    onglet = OngletBranche(navigateur, "cowork", principal=True)
    assert onglet.page() is gemini and onglet.page() is gemini
    assert gemini.lectures == 1  # pas de nouvelle recherche à chaque message
    gemini.fermee = True  # fenêtre fermée par l'utilisateur
    nouvelle = onglet.page()
    assert nouvelle is not gemini and nouvelle.marque == "cowork"


# ---- port de débogage indisponible (réservé par Windows) -----------------------

import json  # noqa: E402
import threading as _threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

from pilote.chrome import FICHIER_PORT, port_utilisable  # noqa: E402


def faux_chrome():
    class Gestion(BaseHTTPRequestHandler):
        def do_GET(self):
            corps = json.dumps({"Browser": "Chrome/155"}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(corps)

        def log_message(self, *args):
            pass

    serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
    _threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur


def test_port_pris_pas_utilisable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert port_utilisable(s.getsockname()[1]) is False
    assert port_utilisable(port_libre()) is True


def test_port_ecrit_par_chrome_dans_le_profil(tmp_path):
    serveur = faux_chrome()
    try:
        (tmp_path / FICHIER_PORT).write_text(f"{serveur.server_address[1]}\n/devtools/browser/x", encoding="utf-8")
        chrome = ChromeDedie(Path("C:/chrome.exe"), tmp_path, port_libre(), GEMINI)
        assert chrome.est_lance() is True
        assert chrome.port_actuel == serveur.server_address[1]
    finally:
        serveur.shutdown()


def test_port_reserve_chrome_choisit_un_port_libre(tmp_path, monkeypatch):
    from pilote import chrome as module

    with socket.socket() as occupe:
        occupe.bind(("127.0.0.1", 0))
        occupe.listen()
        lances = []
        chrome = ChromeDedie(Path("C:/chrome.exe"), tmp_path, occupe.getsockname()[1], GEMINI)
        monkeypatch.setattr(module.subprocess, "Popen", lambda commande: lances.append(commande))
        monkeypatch.setattr(chrome, "est_lance", lambda: bool(lances))
        chrome.lancer(delai=2)
    assert "--remote-debugging-port=0" in lances[0]


def test_un_autre_programme_sur_le_port_n_est_pas_chrome(tmp_path):
    class Autre(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"autre": true}')

        def log_message(self, *args):
            pass

    serveur = ThreadingHTTPServer(("127.0.0.1", 0), Autre)
    _threading.Thread(target=serveur.serve_forever, daemon=True).start()
    try:
        chrome = ChromeDedie(Path("C:/chrome.exe"), tmp_path, serveur.server_address[1], GEMINI)
        assert chrome.est_lance() is False
    finally:
        serveur.shutdown()
