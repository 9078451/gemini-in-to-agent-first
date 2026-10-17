import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from agent_first.serveur import creer_app
from pilote.erreurs import ChoixBloque, ModeleIntrouvable, PasConnecteGoogle
from pilote.modeles import Modes, Option, ResultatGemini

PAR_DEFAUT = Modes([Option("4 Argon", "Tâches complexes")], [Option("Min.", "Rapide et efficace")])


class FauxPilote:
    def __init__(self) -> None:
        self.recus: list[tuple] = []
        self.erreur: Exception | None = None
        self.duree = 0.0
        self.listes = 0

    def envoyer(self, adresse, texte, modele=None, niveau=None):
        self.recus.append((adresse, texte, modele, niveau))
        time.sleep(self.duree)
        if self.erreur:
            raise self.erreur
        return ResultatGemini(
            reponse=f"écho : {texte}",
            adresse="https://gemini.google.com/app/1",
            html=f"<p>écho : {texte}</p><script>x()</script>",
            modele=modele,
            niveau=niveau,
            duree=1.5,
        )

    def est_connecte(self):
        return True

    def lister_modes(self):
        self.listes += 1
        return Modes([Option("3.1 Pro", "Raisonnement avancé", True)], [Option("Max.", "Très poussé", True)])


@pytest.fixture
def pilote():
    return FauxPilote()


def demarrer(pilote, tmp_path, delai=2.0, chrome=True):
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, Historique(tmp_path / "historique.db"), delai, lambda: chrome, PAR_DEFAUT)
    return TestClient(app), file


@pytest.fixture
def client(pilote, tmp_path):
    client, file = demarrer(pilote, tmp_path)
    yield client
    file.arreter()


def nouvelle(client, **reglages) -> str:
    return client.post("/api/conversations", json=reglages).json()["id"]


def envoyer(client, conversation, texte, **reglages):
    return client.post(f"/api/conversations/{conversation}/messages", json={"texte": texte, **reglages})


def roles(client, conversation):
    return [m["role"] for m in client.get(f"/api/conversations/{conversation}").json()["messages"]]


def test_modeles_lus_dans_gemini_puis_gardes(client, pilote):
    lus = client.get("/api/modeles").json()
    client.get("/api/modeles")
    assert lus == {
        "modeles": [{"nom": "3.1 Pro", "description": "Raisonnement avancé", "actif": True}],
        "niveaux": [{"nom": "Max.", "description": "Très poussé", "actif": True}],
    }
    assert pilote.listes == 1


def test_modeles_par_defaut_si_chrome_ferme(pilote, tmp_path):
    client, file = demarrer(pilote, tmp_path, chrome=False)
    assert client.get("/api/modeles").json()["modeles"][0]["nom"] == "4 Argon"
    assert pilote.listes == 0
    file.arreter()


def test_conversation_complete(client, pilote):
    conversation = nouvelle(client)
    r = envoyer(client, conversation, "Bonjour", modele="3.1 Pro", niveau="Max.")
    assert r.status_code == 200
    m = r.json()["message"]
    assert (m["role"], m["texte"], m["modele"], m["niveau"], m["duree"]) == ("gemini", "écho : Bonjour", "3.1 Pro", "Max.", 1.5)
    envoyer(client, conversation, "Et ensuite ?", modele="3.1 Pro", niveau="Max.")
    assert pilote.recus == [
        (None, "Bonjour", "3.1 Pro", "Max."),
        ("https://gemini.google.com/app/1", "Et ensuite ?", "3.1 Pro", "Max."),
    ]
    lue = client.get(f"/api/conversations/{conversation}").json()
    assert lue["conversation"]["titre"] == "Bonjour"
    assert [m["role"] for m in lue["messages"]] == ["toi", "gemini", "toi", "gemini"]


def test_reponse_html_nettoyee(client):
    m = envoyer(client, nouvelle(client), "Bonjour").json()["message"]
    assert m["html"] == "<p>écho : Bonjour</p>"


def test_erreur_pilote_enregistree(client, pilote):
    pilote.erreur = PasConnecteGoogle()
    conversation = nouvelle(client)
    r = envoyer(client, conversation, "Bonjour")
    assert r.status_code == 502
    assert r.json()["erreur"] == str(PasConnecteGoogle())
    assert roles(client, conversation) == ["toi", "erreur"]


def test_message_vide_refuse(client, pilote):
    r = envoyer(client, nouvelle(client), "  \n ")
    assert r.status_code == 422
    assert "erreur" in r.json()
    assert pilote.recus == []


def test_conversation_inconnue(client):
    assert envoyer(client, "nexistepas", "Bonjour").status_code == 404
    assert client.get("/api/conversations/nexistepas").status_code == 404
    assert client.delete("/api/conversations/nexistepas").status_code == 404


def test_liste_et_recherche(client):
    envoyer(client, nouvelle(client), "Les phares")
    envoyer(client, nouvelle(client), "Code Python")
    assert [c["titre"] for c in client.get("/api/conversations").json()] == ["Code Python", "Les phares"]
    trouvees = client.get("/api/conversations", params={"recherche": "phares"}).json()
    assert [c["titre"] for c in trouvees] == ["Les phares"]


def test_suppression(client):
    conversation = nouvelle(client)
    envoyer(client, conversation, "Bonjour")
    assert client.delete(f"/api/conversations/{conversation}").json() == {"supprimee": True}
    assert client.get(f"/api/conversations/{conversation}").status_code == 404
    assert client.get("/api/conversations").json() == []


def test_suppression_pendant_envoi(pilote, tmp_path):
    pilote.duree = 0.5
    client, file = demarrer(pilote, tmp_path)
    conversation = nouvelle(client)
    with ThreadPoolExecutor(1) as fil:
        envoi = fil.submit(envoyer, client, conversation, "Bonjour")
        time.sleep(0.2)
        client.delete(f"/api/conversations/{conversation}")
        r = envoi.result(timeout=5)
    assert r.status_code == 200
    assert r.json()["message"]["texte"] == "écho : Bonjour"
    assert client.get(f"/api/conversations/{conversation}").status_code == 404
    file.arreter()


def test_statistiques(client):
    envoyer(client, nouvelle(client), "Bonjour", modele="3.1 Pro")
    assert client.get("/api/statistiques", params={"periode": "7j"}).json() == {
        "conversations": 1, "messages": 1, "modele_favori": "3.1 Pro", "temps_moyen": 1.5, "medias": 0,
    }


def test_modele_introuvable_relit_la_liste(client, pilote):
    client.get("/api/modeles")
    pilote.erreur = ModeleIntrouvable("9 Zeta")
    r = envoyer(client, nouvelle(client), "Bonjour", modele="9 Zeta")
    assert r.status_code == 502
    assert "9 Zeta" in r.json()["erreur"]
    client.get("/api/modeles")
    assert pilote.listes == 2


def test_choix_bloque_relit_la_liste(client, pilote):
    # Les options bloquées par la limite changent de description : l'app doit les revoir.
    client.get("/api/modeles")
    pilote.erreur = ChoixBloque("4 Argon", "16 oct., 14:58")
    r = envoyer(client, nouvelle(client), "Bonjour", modele="4 Argon")
    assert r.status_code == 502
    assert "14:58" in r.json()["erreur"]
    client.get("/api/modeles")
    assert pilote.listes == 2


def test_delai_depasse(pilote, tmp_path):
    pilote.duree = 1.0
    client, file = demarrer(pilote, tmp_path, delai=0.1)
    conversation = nouvelle(client)
    assert envoyer(client, conversation, "Bonjour").status_code == 504
    assert roles(client, conversation) == ["toi", "erreur"]
    file.arreter()


def test_etat(client):
    assert client.get("/api/etat").json() == {"agent_first": True, "chrome": True, "google": True}


def test_page_web_servie_sans_cache(pilote, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>agent.first</title>", encoding="utf-8")
    (web / "app.js").write_text("console.log(1);", encoding="utf-8")
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, Historique(tmp_path / "historique.db"), 2.0, lambda: True, PAR_DEFAUT, dossier_web=web)
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "agent.first" in page.text
    assert page.headers["cache-control"] == "no-cache"
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "cache-control" not in client.get("/api/statistiques").headers
    file.arreter()


def test_api_reseau_infos(pilote, tmp_path):
    from agent_first.cle_api import GardeCle

    garde = GardeCle(tmp_path / "cle.txt")
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, Historique(tmp_path / "historique.db"), 2.0, lambda: True, PAR_DEFAUT,
                    garde_api=garde, adresse_api="http://192.168.1.10:8766/v1")
    client = TestClient(app)
    infos = client.get("/api/api-reseau").json()
    assert infos == {"active": True, "adresse": "http://192.168.1.10:8766/v1", "cle": garde.cle}
    nouvelle = client.post("/api/api-reseau/cle").json()["cle"]
    assert nouvelle == garde.cle and nouvelle != infos["cle"]
    file.arreter()


def test_api_reseau_inactive(client):
    assert client.get("/api/api-reseau").json() == {"active": False, "adresse": None, "cle": None}


def test_flux_global_commence_par_l_etat_present():
    import itertools

    from agent_first.diffuseur import Diffuseur

    diffuseur = Diffuseur()
    present = [{"conversation_id": "c1", "type": "statut", "statut": "waiting_approval"}]
    premier = next(itertools.islice(diffuseur.flux(lambda: present), 1))
    assert '"waiting_approval"' in premier and premier.startswith("data: ")


def test_hote_inconnu_refuse(pilote, tmp_path):
    # Protège de la « reliure DNS » : une page web ne doit pas pouvoir lire la clé de l'API.
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, Historique(tmp_path / "historique.db"), 2.0, lambda: True, PAR_DEFAUT,
                    hotes_autorises=["127.0.0.1", "localhost"])
    assert TestClient(app, base_url="http://evil.example").get("/api/etat").status_code == 400
    assert TestClient(app, base_url="http://127.0.0.1:8765").get("/api/etat").status_code == 200
    file.arreter()
