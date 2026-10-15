import time

import pytest
from fastapi.testclient import TestClient

from agent_first.conversations import MemoireConversations
from agent_first.file_attente import FileAttente
from agent_first.serveur import creer_app
from pilote.erreurs import PasConnecteGoogle
from pilote.modeles import ResultatGemini


class FauxPilote:
    def __init__(self) -> None:
        self.recus: list[tuple[str | None, str]] = []
        self.erreur: Exception | None = None
        self.duree = 0.0

    def envoyer(self, adresse, texte):
        self.recus.append((adresse, texte))
        time.sleep(self.duree)
        if self.erreur:
            raise self.erreur
        return ResultatGemini(reponse=f"écho : {texte}", adresse="https://gemini.google.com/app/1")

    def est_connecte(self):
        return True


@pytest.fixture
def pilote():
    return FauxPilote()


@pytest.fixture
def client(pilote, tmp_path):
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, MemoireConversations(tmp_path / "conv.json"), delai=2.0, chrome_lance=lambda: True)
    yield TestClient(app)
    file.arreter()


def nouvelle(client) -> str:
    return client.post("/conversations").json()["conversation"]


def test_premier_message_puis_suite(client, pilote):
    conv = nouvelle(client)
    r1 = client.post("/message", json={"conversation": conv, "texte": "Bonjour"})
    assert r1.status_code == 200
    assert r1.json() == {"conversation": conv, "reponse": "écho : Bonjour"}
    client.post("/message", json={"conversation": conv, "texte": "Et toi ?"})
    assert pilote.recus == [(None, "Bonjour"), ("https://gemini.google.com/app/1", "Et toi ?")]


def test_message_vide_refuse(client, pilote):
    conv = nouvelle(client)
    r = client.post("/message", json={"conversation": conv, "texte": "   \n "})
    assert r.status_code == 422
    assert "erreur" in r.json()
    assert pilote.recus == []


def test_conversation_inconnue(client):
    r = client.post("/message", json={"conversation": "nexistepas", "texte": "Bonjour"})
    assert r.status_code == 404
    assert "nouvelle conversation" in r.json()["erreur"]


def test_erreur_pilote_transmise(client, pilote):
    pilote.erreur = PasConnecteGoogle()
    r = client.post("/message", json={"conversation": nouvelle(client), "texte": "Bonjour"})
    assert r.status_code == 502
    assert r.json()["erreur"] == str(PasConnecteGoogle())


def test_delai_depasse(pilote, tmp_path):
    pilote.duree = 1.0
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, MemoireConversations(tmp_path / "conv.json"), delai=0.1, chrome_lance=lambda: True)
    client = TestClient(app)
    r = client.post("/message", json={"conversation": nouvelle(client), "texte": "Bonjour"})
    assert r.status_code == 504
    file.arreter()


def test_etat_chrome_ferme(pilote, tmp_path):
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, MemoireConversations(tmp_path / "conv.json"), delai=2.0, chrome_lance=lambda: False)
    assert TestClient(app).get("/etat").json() == {"agent_first": True, "chrome": False, "google": None}
    file.arreter()


def test_etat_chrome_ouvert(client):
    assert client.get("/etat").json() == {"agent_first": True, "chrome": True, "google": True}
