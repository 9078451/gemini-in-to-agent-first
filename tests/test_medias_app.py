"""Créer des images, des vidéos et de la musique depuis l'app, et les retrouver."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from agent_first.mediatheque import Mediatheque
from agent_first.serveur import creer_app
from pilote.modeles import Media, Modes, Option, ResultatGemini

PAR_DEFAUT = Modes([Option("4 Argon", "Tâches complexes", True)], [Option("Min.", "Rapide et efficace", True)])
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


class PiloteMedias:
    def __init__(self) -> None:
        self.envois: list[dict] = []
        self.medias: tuple[Media, ...] = (Media("image", "image/png", PNG, "un chat roux"),)
        self.duree = 0.0

    def envoyer(self, adresse, texte, modele=None, niveau=None, delai=None, outil=None):
        self.envois.append({"adresse": adresse, "texte": texte, "delai": delai, "outil": outil})
        time.sleep(self.duree)
        return ResultatGemini(
            reponse="Gemini a dit\nVoici ton image.", adresse="https://gemini.google.com/app/1",
            modele=modele, niveau=niveau, duree=3.0, medias=self.medias if outil else (),
        )

    def est_connecte(self):
        return True

    def lister_modes(self):
        return PAR_DEFAUT


@pytest.fixture
def monte(tmp_path):
    files = []

    def monter(delai=5.0, delais_media=None):
        pilote = PiloteMedias()
        file = FileAttente(lambda: pilote)
        file.demarrer()
        files.append(file)
        mediatheque = Mediatheque(tmp_path / "medias")
        app = creer_app(
            file, Historique(tmp_path / "historique.db"), delai, lambda: True, PAR_DEFAUT,
            mediatheque=mediatheque, delais_media=delais_media or {"image": 240.0, "video": 900.0}, attente_file=1.0,
        )
        return TestClient(app), pilote

    yield monter
    for file in files:
        file.arreter()


def creer_image(client, texte="un chat roux sur un toit"):
    conversation = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{conversation}/messages", json={"texte": texte, "outil": "image"})
    return conversation, r


def test_image_creee_gardee_et_servie(monte):
    client, pilote = monte()
    conversation, r = creer_image(client)
    assert r.status_code == 200
    message = r.json()["message"]
    assert message["texte"] == "Voici ton image."  # sans « Gemini a dit »
    [media] = message["medias"]
    assert (media["type"], media["mime"], media["octets"], media["description"]) == ("image", "image/png", len(PNG), "un chat roux")
    servi = client.get(f"/api/medias/{media['id']}")
    assert servi.status_code == 200 and servi.content == PNG
    assert servi.headers["content-type"] == "image/png"
    assert "sandbox" in servi.headers["content-security-policy"]
    assert servi.headers["content-disposition"].startswith("inline")
    assert client.get(f"/api/medias/{media['id']}", params={"telecharger": True}).headers["content-disposition"].startswith("attachment")
    # rouverte plus tard, la conversation garde ses médias
    lue = client.get(f"/api/conversations/{conversation}").json()["messages"]
    assert lue[1]["medias"] == [media] and lue[0]["details"] == '{"outil": "image"}'


def test_demande_redigee_pour_creer_et_delai_du_media(monte):
    client, pilote = monte()
    creer_image(client, "un chat roux")
    envoi = pilote.envois[0]
    assert envoi["outil"] == "image" and envoi["delai"] == 240.0
    assert envoi["texte"].startswith("Génère une image") and envoi["texte"].endswith("Demande : un chat roux")
    conversation = client.get("/api/conversations").json()[0]["id"]
    # l'historique garde la demande telle qu'écrite
    assert client.get(f"/api/conversations/{conversation}").json()["messages"][0]["texte"] == "un chat roux"


def test_suite_d_une_creation_peut_modifier_le_media(monte):
    client, pilote = monte()
    conversation, _ = creer_image(client)
    client.post(f"/api/conversations/{conversation}/messages", json={"texte": "en violet", "outil": "image"})
    assert "modifie-le" in pilote.envois[1]["texte"] and pilote.envois[1]["adresse"] is not None


def test_message_ecrit_sans_outil_ni_delai(monte):
    client, pilote = monte()
    conversation = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{conversation}/messages", json={"texte": "Bonjour"})
    assert r.json()["message"]["medias"] == []
    assert pilote.envois[0] == {"adresse": None, "texte": "Bonjour", "delai": None, "outil": None}


def test_outil_inconnu_refuse(monte):
    client, _ = monte()
    conversation = client.post("/api/conversations", json={}).json()["id"]
    assert client.post(f"/api/conversations/{conversation}/messages", json={"texte": "x", "outil": "hologramme"}).status_code == 422


def test_retirer_la_conversation_retire_ses_medias(monte):
    client, _ = monte()
    conversation, r = creer_image(client)
    media = r.json()["message"]["medias"][0]["id"]
    client.delete(f"/api/conversations/{conversation}")
    assert client.get(f"/api/medias/{media}").status_code == 404


def test_media_mal_designe_404(monte):
    client, _ = monte()
    assert client.get("/api/medias/..%2F..%2Fconfig.py/x").status_code == 404
    assert client.get("/api/medias/0123456789abcdef0123456789abcdef/abcdefabcdef.png").status_code == 404


def test_un_media_a_plus_de_temps_qu_un_message(monte):
    # Une vidéo peut prendre des minutes : la limite du Chat (ici 0,2 s) ne s'applique pas.
    client, pilote = monte(delai=0.2, delais_media={"video": 2.0})
    pilote.duree = 0.5
    pilote.medias = (Media("video", "video/mp4", MP4),)
    conversation = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{conversation}/messages", json={"texte": "un lever de soleil", "outil": "video"})
    assert r.status_code == 200 and r.json()["message"]["medias"][0]["mime"] == "video/mp4"


def test_demande_en_file_retiree_apres_le_delai(monte):
    # Sans réponse à temps, la demande qui attendait son tour ne part plus vers Gemini plus tard.
    client, pilote = monte(delai=0.2)
    pilote.duree = 0.6
    a = client.post("/api/conversations", json={}).json()["id"]
    b = client.post("/api/conversations", json={}).json()["id"]
    reponses = {}
    premier = threading.Thread(target=lambda: reponses.setdefault("a", client.post(f"/api/conversations/{a}/messages", json={"texte": "un"})))
    premier.start()
    time.sleep(0.05)
    assert client.post(f"/api/conversations/{b}/messages", json={"texte": "deux"}).status_code == 504
    premier.join()
    time.sleep(0.8)
    assert [e["texte"] for e in pilote.envois] == ["un"]


def test_etat_sans_attendre_l_onglet_occupe(monte):
    client, pilote = monte(delai=5.0)
    assert client.get("/api/etat").json()["google"] is True
    pilote.duree = 1.0
    conversation = client.post("/api/conversations", json={}).json()["id"]
    envoi = threading.Thread(target=lambda: client.post(f"/api/conversations/{conversation}/messages", json={"texte": "x"}))
    envoi.start()
    time.sleep(0.1)
    debut = time.monotonic()
    assert client.get("/api/etat").json()["google"] is True  # le dernier état lu
    assert time.monotonic() - debut < 0.5
    envoi.join()


def test_statistiques_comptent_les_medias(monte):
    client, _ = monte()
    creer_image(client)
    assert client.get("/api/statistiques", params={"periode": "tout"}).json()["medias"] == 1


def test_reponse_tardive_gardee_dans_l_historique(monte):
    client, pilote = monte(delai=0.2)
    pilote.duree = 0.5
    conversation = client.post("/api/conversations", json={}).json()["id"]
    assert client.post(f"/api/conversations/{conversation}/messages", json={"texte": "x"}).status_code == 504
    time.sleep(0.6)
    roles = [m["role"] for m in client.get(f"/api/conversations/{conversation}").json()["messages"]]
    assert roles == ["toi", "erreur", "gemini"]
