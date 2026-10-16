import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent_first.cowork_service import ServiceCowork
from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from agent_first.serveur import creer_app
from cowork.actions import Executeur
from pilote.modeles import Modes, Option, ResultatGemini

PAR_DEFAUT = Modes([Option("4 Argon", "Tâches complexes")], [Option("Min.", "Rapide et efficace")])


class FauxPilote:
    """Renvoie des réponses Cowork scriptées, quels que soient adresse/modèle."""

    def __init__(self, reponses):
        self._reponses = list(reponses)

    def envoyer(self, adresse, texte, modele=None, niveau=None):
        reponse = self._reponses.pop(0) if self._reponses else "TERMINÉ"
        return ResultatGemini(reponse=reponse, adresse="https://gemini.google.com/app/1")

    def est_connecte(self):
        return True

    def lister_modes(self):
        return PAR_DEFAUT


def monter(tmp_path, reponses, choisir=None):
    pilote = FauxPilote(reponses)
    file = FileAttente(lambda: pilote)
    file.demarrer()
    historique = Historique(tmp_path / "historique.db")
    service = ServiceCowork(
        file, historique, lambda dossier: Executeur(dossier, 5, 8000, lancer=lambda *a: (0, "sortie")),
        max_etapes=40, echecs_max=3, taille_max=8000,
    )
    app = creer_app(file, historique, 2.0, lambda: True, PAR_DEFAUT, cowork=service,
                    choisir_dossier=choisir or (lambda: str(tmp_path)))
    return TestClient(app), file, historique, service


def drainer_dans(service, conversation_id, sortie):
    """Empile chaque évènement du flux dans `sortie` dès son arrivée."""
    for ligne in service.flux(conversation_id):
        if ligne.startswith("data:"):
            sortie.append(json.loads(ligne[5:].strip()))


def evenements(service, conversation_id):
    sortie = []
    drainer_dans(service, conversation_id, sortie)
    return sortie


def test_conversation_cowork_cree_avec_dossier(tmp_path):
    client, file, *_ = monter(tmp_path, [])
    r = client.post("/api/conversations", json={"mode": "cowork", "dossier": str(tmp_path)})
    assert (r.json()["mode"], r.json()["dossier"]) == ("cowork", str(tmp_path))
    file.arreter()


def test_choisir_dossier(tmp_path):
    client, file, *_ = monter(tmp_path, [], choisir=lambda: str(tmp_path))
    assert client.post("/api/dossiers/choisir").json()["dossier"] == str(tmp_path)
    file.arreter()


def test_tache_cowork_cree_un_fichier(tmp_path):
    reponses = ['```json\n{"action":"creer","chemin":"a.txt","contenu":"salut"}\n```', "TERMINÉ : fait"]
    client, file, historique, service = monter(tmp_path, reponses)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "crée a.txt"})
    evs = evenements(service, conv.id)
    assert [e["type"] for e in evs][-1] == "termine"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "salut"
    file.arreter()


def test_etapes_enregistrees(tmp_path):
    reponses = ['```json\n{"action":"lister","chemin":"."}\n```', "TERMINÉ"]
    client, file, historique, service = monter(tmp_path, reponses)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "liste"})
    evenements(service, conv.id)
    etapes = client.get(f"/api/conversations/{conv.id}").json()["messages"]
    assert any(m["role"] == "cowork" for m in etapes)
    file.arreter()


def test_decision_debloque_une_action_dangereuse(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    reponses = ['```json\n{"action":"supprimer","chemin":"a.txt"}\n```', "TERMINÉ"]
    client, file, historique, service = monter(tmp_path, reponses)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    collectes = []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime a.txt"})
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, collectes))
    fil.start()
    for _ in range(50):  # attendre l'évènement « demande »
        if any(e["type"] == "demande" for e in collectes):
            break
        time.sleep(0.05)
    demande = next(e for e in collectes if e["type"] == "demande")
    client.post(f"/api/cowork/{conv.id}/decision", json={"etape": demande["etape"], "reponse": "continuer"})
    fil.join(timeout=5)
    assert not (tmp_path / "a.txt").exists()
    file.arreter()
