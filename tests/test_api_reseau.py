import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent_first.api_reseau import creer_api_reseau
from agent_first.cache_modes import CacheModes
from agent_first.cle_api import GardeCle
from agent_first.cowork_service import ServiceCowork
from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from cowork.actions import Executeur
from cowork.boucle import Reglages
from cowork.processus import GestionnaireProcessus
from pilote.erreurs import ErreurPilote
from pilote.modeles import Modes, Option, ResultatGemini

PAR_DEFAUT = Modes([Option("4 Argon", "Tâches complexes", True), Option("3.1 Pro", "Raisonnement")],
                   [Option("Min.", "Rapide et efficace", True)])
REGLAGES = Reglages(max_tours=40, max_actions=10, echecs_max=3, taille_max=8000, taille_max_message=30000, relances_fin_max=2)
FINI = '```json\n{"action": "done", "summary": "fait"}\n```'


class FauxPilote:
    def __init__(self, reponses=(), erreur=None):
        self._reponses = list(reponses)
        self._erreur = erreur
        self.envois = []

    def envoyer(self, adresse, texte, modele=None, niveau=None, delai=None):
        if self._erreur:
            raise self._erreur
        self.envois.append({"adresse": adresse, "texte": texte, "modele": modele, "niveau": niveau})
        reponse = self._reponses.pop(0) if self._reponses else "Gemini a dit\nRéponse"
        return ResultatGemini(reponse=reponse, adresse=f"https://gemini.google.com/app/{len(self.envois)}", modele=modele)

    def est_connecte(self):
        return True

    def lister_modes(self):
        return PAR_DEFAUT


@pytest.fixture
def monte(tmp_path):
    montes = []

    def monter(reponses=(), erreur=None):
        pilote = FauxPilote(reponses, erreur)
        file = FileAttente(lambda: pilote)
        file.demarrer()
        historique = Historique(tmp_path / "historique.db")
        service = ServiceCowork(
            file, historique,
            lambda dossier, processus, arret: Executeur(dossier, 5, 8000, lancer=lambda *a, **k: (0, "sortie"), processus=processus, arret=arret),
            REGLAGES,
            lambda dossier, au_changement: GestionnaireProcessus(dossier, 3, 0.3, 8000, au_changement=au_changement),
        )
        garde = GardeCle(tmp_path / "cle.txt")
        api = creer_api_reseau(file, historique, service, garde, CacheModes(file, lambda: True, PAR_DEFAUT), 2.0)
        client = TestClient(api, headers={"Authorization": f"Bearer {garde.cle}"})
        montes.append(file)
        return client, pilote, historique, service

    yield monter
    for file in montes:
        file.arreter()


def evenements_sse(reponse):
    return [json.loads(l[len("data: "):]) for l in reponse.text.splitlines() if l.startswith("data: ") and l != "data: [DONE]"]


def test_sans_cle_401(monte):
    client, *_ = monte()
    r = client.get("/v1/models", headers={"Authorization": ""})
    assert r.status_code == 401 and r.json()["error"]["type"] == "authentication_error"


def test_docs_sans_cle(monte):
    client, *_ = monte()
    assert client.get("/docs", headers={"Authorization": ""}).status_code == 200


def test_models(monte):
    client, *_ = monte()
    donnees = client.get("/v1/models").json()
    assert donnees["object"] == "list" and [m["id"] for m in donnees["data"]] == ["4 Argon", "3.1 Pro"]


def test_chat_completion(monte):
    client, pilote, historique, _ = monte()
    r = client.post("/v1/chat/completions", json={"model": "4 Argon", "messages": [{"role": "user", "content": "Salut"}]})
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "Réponse"
    assert pilote.envois[0] == {"adresse": None, "texte": "Salut", "modele": "4 Argon", "niveau": None}
    conversations = historique.lister()
    assert len(conversations) == 1 and conversations[0].source == "api"


def test_suite_de_conversation(monte):
    client, pilote, *_ = monte()
    premier = [{"role": "user", "content": "Salut"}]
    reponse = client.post("/v1/chat/completions", json={"model": "4 Argon", "messages": premier}).json()
    suite = premier + [reponse["choices"][0]["message"], {"role": "user", "content": "Et toi ?"}]
    client.post("/v1/chat/completions", json={"model": "4 Argon", "messages": suite})
    assert pilote.envois[1]["texte"] == "Et toi ?" and pilote.envois[1]["adresse"] == "https://gemini.google.com/app/1"


def test_historique_inconnu_mis_a_plat(monte):
    client, pilote, *_ = monte()
    messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    client.post("/v1/chat/completions", json={"messages": messages})
    assert pilote.envois[0]["adresse"] is None and "[Conversation so far]" in pilote.envois[0]["texte"]


def test_stream(monte):
    client, *_ = monte()
    r = client.post("/v1/chat/completions", json={"stream": True, "messages": [{"role": "user", "content": "Salut"}]})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text.rstrip().endswith("data: [DONE]") and "Réponse" in r.text


def test_reasoning_effort(monte):
    client, pilote, *_ = monte()
    client.post("/v1/chat/completions", json={"reasoning_effort": "high", "messages": [{"role": "user", "content": "x"}]})
    assert pilote.envois[0]["niveau"] == "Max."


def test_sans_message_400(monte):
    client, *_ = monte()
    r = client.post("/v1/chat/completions", json={"messages": []})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"


def test_erreur_pilote_502(monte):
    client, *_ = monte(erreur=ErreurPilote("Google demande une vérification"))
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 502 and "vérification" in r.json()["error"]["message"]


def test_cowork_cree_et_suit(monte, tmp_path):
    client, *_ = monte([FINI])
    r = client.post("/v1/cowork", json={"folder": str(tmp_path), "request": "range le dossier"})
    assert r.status_code == 200 and set(r.json()) == {"id", "status"}
    evs = evenements_sse(client.get(f"/v1/cowork/{r.json()['id']}/events"))
    fin = [e for e in evs if e["type"] == "done"][0]
    assert fin["summary"] == "fait" and fin["report"]["created"] == []
    etat = client.get(f"/v1/cowork/{r.json()['id']}").json()
    assert etat["status"] == "done" and etat["summary"] == "fait"


def test_cowork_dossier_refuse(monte, tmp_path):
    client, *_ = monte()
    for dossier in ("C:\\", "C:\\Windows", str(tmp_path / "absent"), "relatif"):
        r = client.post("/v1/cowork", json={"folder": dossier, "request": "x"})
        assert r.status_code == 400, dossier


def test_cowork_decision(monte, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, *_ = monte(['```json\n{"action": "delete", "path": "a.txt"}\n```', FINI])
    identifiant = client.post("/v1/cowork", json={"folder": str(tmp_path), "request": "supprime a.txt"}).json()["id"]
    fin = time.monotonic() + 5
    while client.get(f"/v1/cowork/{identifiant}").json()["status"] != "waiting_approval":
        assert time.monotonic() < fin
        time.sleep(0.05)
    demande = [e for e in client.get(f"/v1/cowork/{identifiant}").json()["events"] if e["type"] == "approval_required"][0]
    client.post(f"/v1/cowork/{identifiant}/decision", json={"step": demande["step"], "approve": True})
    evenements_sse(client.get(f"/v1/cowork/{identifiant}/events"))
    assert not (tmp_path / "a.txt").exists()


def test_cowork_409_et_suite(monte, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, *_ = monte(['```json\n{"action": "delete", "path": "a.txt"}\n```'])
    identifiant = client.post("/v1/cowork", json={"folder": str(tmp_path), "request": "supprime"}).json()["id"]
    fin = time.monotonic() + 5
    while client.get(f"/v1/cowork/{identifiant}").json()["status"] != "waiting_approval":
        assert time.monotonic() < fin
        time.sleep(0.05)
    assert client.post(f"/v1/cowork/{identifiant}/messages", json={"text": "encore"}).status_code == 409
    client.post(f"/v1/cowork/{identifiant}/stop")
    evenements_sse(client.get(f"/v1/cowork/{identifiant}/events"))
    r = client.post(f"/v1/cowork/{identifiant}/messages", json={"text": "recommence"})
    assert r.status_code == 200


def test_cowork_inconnu_404(monte):
    client, *_ = monte()
    assert client.get("/v1/cowork/absent").status_code == 404
    assert client.post("/v1/cowork/absent/messages", json={"text": "x"}).status_code == 404
