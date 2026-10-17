"""Images, vidéos et musique par l'API réseau ; flux robuste ; noms de modèles tolérants."""
import base64
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
from agent_first.mediatheque import Mediatheque
from cowork.actions import Executeur
from cowork.boucle import Reglages
from cowork.processus import GestionnaireProcessus
from pilote.erreurs import ErreurPilote
from pilote.modeles import Media, Modes, Option, ResultatGemini

PAR_DEFAUT = Modes([Option("3.5 Flash", "Aide", True), Option("3.1 Pro", "Raisonnement")], [Option("Min.", "", True)])
REGLAGES = Reglages(max_tours=40, max_actions=10, echecs_max=3, taille_max=8000, taille_max_message=30000, relances_fin_max=2)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 32
MP3 = b"ID3" + b"\x00" * 32


class PiloteMedias:
    def __init__(self) -> None:
        self.envois: list[dict] = []
        self.duree = 0.0
        self.erreur: Exception | None = None
        self.reponses: list[tuple[Media, ...]] = []  # médias de chaque réponse, dans l'ordre

    def envoyer(self, adresse, texte, modele=None, niveau=None, delai=None, outil=None):
        self.envois.append({"adresse": adresse, "texte": texte, "modele": modele, "niveau": niveau, "outil": outil})
        time.sleep(self.duree)
        if self.erreur:
            raise self.erreur
        medias = self.reponses.pop(0) if self.reponses else ()
        return ResultatGemini(reponse="Gemini a dit\nVoilà.", adresse=f"https://gemini.google.com/app/{len(self.envois)}",
                              modele=modele, medias=medias)

    def est_connecte(self):
        return True

    def lister_modes(self):
        return PAR_DEFAUT


@pytest.fixture
def monte(tmp_path):
    files = []

    def monter(delai=5.0):
        pilote = PiloteMedias()
        file = FileAttente(lambda: pilote)
        file.demarrer()
        files.append(file)
        historique = Historique(tmp_path / "historique.db")
        service = ServiceCowork(
            file, historique,
            lambda dossier, processus, arret: Executeur(dossier, 5, 8000, lancer=lambda *a, **k: (0, ""), processus=processus, arret=arret),
            REGLAGES,
            lambda dossier, au_changement: GestionnaireProcessus(dossier, 3, 0.3, 8000, au_changement=au_changement),
        )
        garde = GardeCle(tmp_path / "cle.txt")
        api = creer_api_reseau(
            file, historique, service, garde, CacheModes(file, lambda: True, PAR_DEFAUT), delai,
            mediatheque=Mediatheque(tmp_path / "medias"), delais_media={"image": 5.0, "video": 5.0, "musique": 5.0},
            attente_file=1.0,
        )
        client = TestClient(api, headers={"Authorization": f"Bearer {garde.cle}"})
        return client, pilote, historique

    yield monter
    for file in files:
        file.arreter()


def image(description="un chat"):
    return (Media("image", "image/png", PNG, description),)


def test_images_generations_url_signee_lisible_sans_cle(monte):
    client, pilote, historique = monte()
    pilote.reponses = [image()]
    r = client.post("/v1/images/generations", json={"prompt": "un chat roux", "size": "1792x1024"})
    assert r.status_code == 200
    [donnee] = r.json()["data"]
    assert pilote.envois[0]["outil"] == "image" and "format paysage (16:9)" in pilote.envois[0]["texte"]
    assert donnee["revised_prompt"] == "Voilà."
    url = donnee["url"]
    assert url.startswith("http://testserver/v1/media/") and "sig=" in url
    servi = client.get(url, headers={"Authorization": ""})  # un lien signé s'ouvre sans la clé
    assert servi.status_code == 200 and servi.content == PNG and servi.headers["content-type"] == "image/png"
    sans_signature = url.split("?")[0]
    assert client.get(sans_signature, headers={"Authorization": ""}).status_code == 401
    assert client.get(sans_signature).status_code == 200  # avec la clé
    assert client.get(sans_signature + "?sig=fausse", headers={"Authorization": ""}).status_code == 401
    # la création apparaît dans l'historique de l'app, marquée « api »
    assert historique.lister()[0].source == "api"


def test_images_generations_b64_et_plusieurs(monte):
    client, pilote, _ = monte()
    pilote.reponses = [image("a"), image("b")]
    r = client.post("/v1/images/generations", json={"prompt": "un chat", "n": 2, "response_format": "b64_json"})
    assert r.status_code == 200
    assert [base64.b64decode(d["b64_json"]) for d in r.json()["data"]] == [PNG, PNG]
    # la 2ᵉ image est une variante demandée dans la même conversation Gemini
    assert pilote.envois[1]["adresse"] == "https://gemini.google.com/app/1" and "autre version" in pilote.envois[1]["texte"]


def test_images_generations_sans_image_502_avec_la_reponse(monte):
    client, pilote, _ = monte()
    r = client.post("/v1/images/generations", json={"prompt": "x"})
    assert r.status_code == 502 and "did not create any image" in r.json()["error"]["message"]
    assert "Voilà." in r.json()["error"]["message"] and len(pilote.envois) == 1  # pas d'insistance


def test_media_generations_musique(monte):
    client, pilote, _ = monte()
    pilote.reponses = [(Media("audio", "audio/mpeg", MP3),)]
    r = client.post("/v1/media/generations", json={"type": "music", "prompt": "un air de jazz"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["status"] == "completed" and corps["type"] == "music"
    assert pilote.envois[0]["outil"] == "musique" and pilote.envois[0]["texte"].startswith("Génère un morceau de musique")
    [media] = corps["data"]
    assert media["type"] == "audio" and media["mime_type"] == "audio/mpeg" and client.get(media["url"]).content == MP3


def test_media_generations_type_inconnu_400(monte):
    client, *_ = monte()
    r = client.post("/v1/media/generations", json={"type": "hologramme", "prompt": "x"})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"


def test_media_generations_sans_attendre_puis_suivi(monte):
    client, pilote, _ = monte()
    pilote.duree = 0.4
    pilote.reponses = [(Media("video", "video/mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8),)]
    r = client.post("/v1/media/generations", json={"type": "video", "prompt": "un lever de soleil", "wait": False})
    assert r.status_code == 202 and r.json()["status"] == "in_progress"
    identifiant = r.json()["id"]
    fin = time.monotonic() + 5
    while (etat := client.get(f"/v1/media/generations/{identifiant}").json())["status"] == "in_progress":
        assert time.monotonic() < fin
        time.sleep(0.05)
    assert etat["status"] == "completed" and etat["data"][0]["mime_type"] == "video/mp4"


def test_suivi_retrouve_dans_l_historique_apres_redemarrage(monte):
    client, pilote, _ = monte()
    pilote.reponses = [image()]
    identifiant = client.post("/v1/media/generations", json={"type": "image", "prompt": "un chat"}).json()["id"]
    client2, *_ = monte()  # nouvelle API sur le même historique : rien en mémoire
    etat = client2.get(f"/v1/media/generations/{identifiant}").json()
    assert etat["status"] == "completed" and etat["prompt"] == "un chat" and len(etat["data"]) == 1
    assert client2.get("/v1/media/generations/absent").status_code == 404


def test_chat_avec_modalities_image(monte):
    client, pilote, _ = monte()
    pilote.reponses = [image()]
    r = client.post("/v1/chat/completions", json={
        "model": "gemini-3.1-pro", "modalities": ["image", "text"],
        "messages": [{"role": "user", "content": "Dessine un chat"}],
    })
    assert r.status_code == 200
    message = r.json()["choices"][0]["message"]
    assert pilote.envois[0]["outil"] == "image" and pilote.envois[0]["modele"] == "3.1 Pro"
    assert message["content"].startswith("Voilà.\n\n![Image](http://testserver/v1/media/")
    assert message["images"][0]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert message["media"][0]["type"] == "image"
    # la suite de la conversation est reconnue malgré les liens ajoutés au texte
    suite = [{"role": "user", "content": "Dessine un chat"}, message, {"role": "user", "content": "Merci"}]
    client.post("/v1/chat/completions", json={"model": "gemini-3.1-pro", "messages": suite})
    assert pilote.envois[1]["adresse"] == "https://gemini.google.com/app/1" and pilote.envois[1]["texte"] == "Merci"


def test_chat_media_video(monte):
    client, pilote, _ = monte()
    client.post("/v1/chat/completions", json={"media": "video", "messages": [{"role": "user", "content": "une vague"}]})
    assert pilote.envois[0]["outil"] == "video" and "Veo" in pilote.envois[0]["texte"]


def test_modele_inconnu_prend_le_modele_courant(monte):
    client, pilote, _ = monte()
    r = client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200 and pilote.envois[0]["modele"] is None and r.json()["model"] == "agent-first"


def test_erreur_notee_dans_l_historique(monte):
    client, pilote, historique = monte()
    pilote.erreur = ErreurPilote("Gemini est indisponible")
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 502
    conversation = historique.lister()[0]
    assert [m.role for m in historique.messages(conversation.id)] == ["toi", "erreur"]


def test_flux_garde_la_connexion_puis_repond(monte, monkeypatch):
    import agent_first.api_reseau as api_reseau

    monkeypatch.setattr(api_reseau, "PING", 0.05)
    client, pilote, _ = monte()
    pilote.duree = 0.3
    r = client.post("/v1/chat/completions", json={"stream": True, "messages": [{"role": "user", "content": "x"}]})
    assert r.text.startswith(": ping") and "Voilà." in r.text and r.text.rstrip().endswith("data: [DONE]")


def test_flux_erreur_au_format_openai(monte):
    client, pilote, _ = monte()
    pilote.erreur = ErreurPilote("Gemini est indisponible")
    r = client.post("/v1/chat/completions", json={"stream": True, "messages": [{"role": "user", "content": "x"}]})
    donnees = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: {")]
    assert donnees == [{"error": {"message": "Gemini est indisponible", "type": "upstream_error", "code": 502}}]


def test_reponse_gardee_meme_si_le_client_abandonne(monte):
    # Délai dépassé côté client : la réponse arrivée ensuite est quand même dans l'historique.
    client, pilote, historique = monte(delai=0.2)
    pilote.duree = 0.5
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 504
    time.sleep(0.6)
    conversation = historique.lister()[0]
    assert [m.role for m in historique.messages(conversation.id)] == ["toi", "erreur", "gemini"]


def test_conversation_et_ses_medias(monte):
    client, pilote, _ = monte()
    pilote.reponses = [image()]
    identifiant = client.post("/v1/media/generations", json={"type": "image", "prompt": "un chat"}).json()["id"]
    lue = client.get(f"/v1/conversations/{identifiant}").json()
    assert [m["role"] for m in lue["messages"]] == ["user", "assistant"]
    assert lue["messages"][1]["media"][0]["url"].startswith("http://testserver/v1/media/")


def test_modele_par_son_nom_et_sante(monte):
    client, *_ = monte()
    assert client.get("/v1/models/3.1 Pro").json()["id"] == "3.1 Pro"
    assert client.get("/v1/models/inexistant").status_code == 404
    assert client.get("/health", headers={"Authorization": ""}).json() == {"ok": True}


def test_cors_pour_les_pages_web(monte):
    client, *_ = monte()
    r = client.options("/v1/chat/completions", headers={
        "Origin": "http://192.168.1.20:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] in ("*", "http://192.168.1.20:3000")


def test_deux_demandes_en_meme_temps_passent_l_une_apres_l_autre(monte):
    client, pilote, _ = monte()
    pilote.duree = 0.2
    codes = []

    def appeler(texte):
        codes.append(client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": texte}]}).status_code)

    fils = [threading.Thread(target=appeler, args=(t,)) for t in ("a", "b")]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert codes == [200, 200] and sorted(e["texte"] for e in pilote.envois) == ["a", "b"]
