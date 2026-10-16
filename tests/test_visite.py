import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cowork.visite import visiter


class _Gestionnaire(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/absent":
            self._repondre(404, b"rien ici")
        else:
            self._repondre(200, b"<h1>Bonjour</h1>")

    def do_POST(self):
        longueur = int(self.headers.get("Content-Length", 0))
        self._repondre(201, b"recu:" + self.rfile.read(longueur))

    def _repondre(self, code, corps):
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *args):
        pass


@pytest.fixture
def port():
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _Gestionnaire)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield serveur.server_address[1]
    serveur.shutdown()
    serveur.server_close()


def visite(url, methode="GET", corps=None, interdits=frozenset()):
    return visiter(url, methode, corps, interdits, 5.0, 8000)


def test_visite_get(port):
    r = visite(f"http://localhost:{port}/")
    assert r.ok and r.corps.startswith("HTTP 200 text/html 16 bytes") and "<h1>Bonjour</h1>" in r.corps


def test_visite_post_avec_corps(port):
    r = visite(f"http://127.0.0.1:{port}/api", "POST", '{"a": 1}')
    assert r.ok and r.corps.startswith("HTTP 201") and 'recu:{"a": 1}' in r.corps


def test_visite_erreur_http(port):
    r = visite(f"http://localhost:{port}/absent")
    assert r.ok is False and r.corps.startswith("HTTP 404") and "rien ici" in r.corps


def test_visite_hors_localhost():
    r = visite("http://example.com/")
    assert r.ok is False and "only localhost" in r.corps


def test_visite_schema_refuse():
    assert visite("file:///C:/Windows/win.ini").ok is False


def test_visite_port_interdit(port):
    r = visite(f"http://localhost:{port}/", interdits=frozenset({port}))
    assert r.ok is False and "not allowed" in r.corps


def test_visite_port_par_defaut_interdit():
    assert visite("http://localhost/", interdits=frozenset({80})).ok is False


def test_visite_refusee():
    with socket.socket() as s:  # un port libéré : personne n'y écoute
        s.bind(("127.0.0.1", 0))
        libre = s.getsockname()[1]
    r = visite(f"http://127.0.0.1:{libre}/")
    assert r.ok is False and "connection" in r.corps


def test_visite_reponse_invalide():
    # Un programme local qui ne parle pas HTTP ne doit pas faire planter la tâche.
    serveur = socket.socket()
    serveur.bind(("127.0.0.1", 0))
    serveur.listen()

    def repondre_n_importe_quoi():
        connexion, _ = serveur.accept()
        connexion.recv(1024)
        connexion.sendall(b"pas du HTTP\r\n\r\n")
        connexion.close()

    threading.Thread(target=repondre_n_importe_quoi, daemon=True).start()
    r = visite(f"http://127.0.0.1:{serveur.getsockname()[1]}/")
    serveur.close()
    assert r.ok is False and "connection" in r.corps
