"""Agent First assemblé avec deux onglets Gemini : une tâche Cowork n'occupe que le sien,
le Chat de l'app et l'API réseau répondent pendant ce temps."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent_first.assemblage import assembler
from agent_first.historique import Historique
from pilote.chrome import ONGLET_CHAT, ONGLET_COWORK
from pilote.modeles import Modes, Option, ResultatGemini

FINI = '```json\n{"action": "done", "summary": "fait"}\n```'


class FauxPilote:
    """Le pilote d'un onglet. Celui de Cowork peut être retenu tant que `libere` n'est pas mis."""

    def __init__(self, role, libere=None):
        self.role = role
        self.fil = threading.current_thread().name
        self.libere = libere
        self.appele = threading.Event()
        self.envois = []

    def envoyer(self, adresse, texte, modele=None, niveau=None, delai=None, **_options):
        self.envois.append(texte)
        self.appele.set()
        if self.libere is not None:
            assert self.libere.wait(10)
        reponse = FINI if self.role == ONGLET_COWORK else f"écho : {texte}"
        return ResultatGemini(reponse=reponse, adresse=f"https://gemini.google.com/app/{self.role}", modele=modele)

    def preparer(self):
        pass

    def est_connecte(self):
        return True

    def lister_modes(self):
        return Modes([Option(f"modèle lu par {self.role}", "", True)], [Option("Min.", "", True)])


@pytest.fixture
def agent(tmp_path):
    libere = threading.Event()
    pilotes = {}

    def fabrique(role):
        pilotes[role] = FauxPilote(role, libere if role == ONGLET_COWORK else None)
        return pilotes[role]

    agent = assembler(fabrique, lambda: True, Historique(tmp_path / "historique.db"), tmp_path / "cle.txt")
    agent.pilotes, agent.libere, agent.dossier = pilotes, libere, tmp_path
    agent.client = TestClient(agent.app, base_url="http://127.0.0.1:8765")
    agent.client_api = TestClient(agent.api, headers={"Authorization": f"Bearer {agent.garde.cle}"})
    yield agent
    libere.set()
    agent.arreter()


def tache_cowork_en_cours(agent):
    """Lance une tâche Cowork et attend que son pilote soit occupé à attendre Gemini."""
    conversation = agent.client.post("/api/conversations", json={"mode": "cowork", "dossier": str(agent.dossier)}).json()
    assert agent.client.post(f"/api/cowork/{conversation['id']}/messages", json={"texte": "range"}).status_code == 200
    fin = time.monotonic() + 5
    while ONGLET_COWORK not in agent.pilotes and time.monotonic() < fin:
        time.sleep(0.01)
    assert agent.pilotes[ONGLET_COWORK].appele.wait(5)
    return conversation["id"]


def test_chaque_pilote_est_fabrique_dans_le_fil_de_sa_file(agent):
    tache_cowork_en_cours(agent)
    agent.client.post("/api/conversations/x/messages", json={"texte": "?"})  # 404, sans effet
    agent.client_api.get("/v1/models")
    assert agent.pilotes[ONGLET_COWORK].fil == "file-gemini-cowork"
    assert agent.pilotes[ONGLET_CHAT].fil == "file-gemini-chat"


def test_le_chat_de_l_app_repond_pendant_une_tache_cowork(agent):
    tache_cowork_en_cours(agent)
    chat = agent.client.post("/api/conversations", json={}).json()["id"]
    debut = time.monotonic()
    r = agent.client.post(f"/api/conversations/{chat}/messages", json={"texte": "Salut"})
    assert r.status_code == 200 and r.json()["message"]["texte"] == "écho : Salut"
    assert time.monotonic() - debut < 2
    assert agent.pilotes[ONGLET_COWORK].envois and not any("Salut" in t for t in agent.pilotes[ONGLET_COWORK].envois)


def test_l_api_repond_pendant_une_tache_cowork(agent):
    tache_cowork_en_cours(agent)
    r = agent.client_api.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "Salut"}]})
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "écho : Salut"


def test_les_modeles_sont_lus_pendant_une_tache_cowork(agent):
    tache_cowork_en_cours(agent)
    ids = [m["id"] for m in agent.client_api.get("/v1/models").json()["data"]]
    assert ids == ["modèle lu par chat", "agent-first"]
    assert agent.client.get("/api/modeles").json()["modeles"][0]["nom"] == "modèle lu par chat"


def test_etat_google_connu_pendant_une_tache_cowork(agent):
    tache_cowork_en_cours(agent)
    assert agent.client.get("/api/etat").json()["google"] is True


def test_la_tache_cowork_finit_dans_son_onglet(agent):
    identifiant = tache_cowork_en_cours(agent)
    agent.libere.set()
    fin = time.monotonic() + 5
    while agent.cowork.en_cours(identifiant) and time.monotonic() < fin:
        time.sleep(0.02)
    etat = agent.client_api.get(f"/v1/cowork/{identifiant}").json()
    assert etat["status"] == "done", json.dumps(etat)
