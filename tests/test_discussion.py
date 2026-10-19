"""Envoi d'un message vers le bon fournisseur : historique à plat quand on en change,
secours quand il est à sa limite, en Chat (app, API réseau) comme en Cowork."""
import json

import pytest
from fastapi.testclient import TestClient

from agent_first.discussion import EchecEnvoi, ServiceChat
from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from agent_first.serveur import creer_app
from fournisseurs.reglages import ReglagesFournisseurs
from fournisseurs.repartiteur import Repartiteur
from fournisseurs.service import ServiceFournisseurs
from pilote.chrome import ONGLET_CHAT, ONGLET_COWORK
from pilote.erreurs import LimiteGemini, ModeleIntrouvable
from pilote.modeles import Modes, Option, ResultatGemini
from tests.test_cowork_api import FINI, evenements, fabrique_executeur, fabrique_processus, fin, REGLAGES, types

PAR_DEFAUT = Modes([Option("4 Argon", "Tâches complexes", True)], [Option("Min.", "", True)])


class FauxPilote:
    def __init__(self, nom, erreur=None, reponse=None):
        self.nom, self.erreur, self.reponse = nom, erreur, reponse
        self.recus = []

    def envoyer(self, adresse, texte, modele=None, niveau=None, delai=None, au_fil=None):
        self.recus.append({"adresse": adresse, "texte": texte, "modele": modele, "niveau": niveau})
        if self.erreur:
            raise self.erreur
        reponse = self.reponse or f"{self.nom} : {texte[-20:]}"
        return ResultatGemini(reponse, f"{self.nom}:conv", "", modele, niveau, 0.5)

    def est_connecte(self):
        return True

    def lister_modes(self):
        return PAR_DEFAUT

    def lister_modeles(self):
        return ["llama3.2", "qwen3"]

    def preparer(self):
        pass


class Monte:
    def __init__(self, tmp_path, gemini=None, ollama=None):
        self.gemini = gemini or FauxPilote("gemini")
        self.ollama = ollama or FauxPilote("ollama")
        self.files = [FileAttente(lambda: self.gemini, nom="g-chat"), FileAttente(lambda: self.gemini, nom="g-cowork")]
        for file in self.files:
            file.demarrer()
        self.repartiteur = Repartiteur(
            {"ollama": lambda role: self.ollama}, {"ollama"},
            existantes={("gemini", ONGLET_CHAT): self.files[0], ("gemini", ONGLET_COWORK): self.files[1]},
        )
        self.reglages = ReglagesFournisseurs(tmp_path / "fournisseurs.json")
        self.reglages.enregistrer("ollama", actif=True)
        self.fournisseurs = ServiceFournisseurs(self.reglages, self.repartiteur)
        self.historique = Historique(tmp_path / "historique.db")
        self.chat = ServiceChat(self.historique, self.fournisseurs, delai=2.0)

    def secours(self, fournisseur="ollama", modele="llama3.2"):
        self.reglages.regler_secours(True, fournisseur, modele)

    def arreter(self):
        self.repartiteur.arreter()


@pytest.fixture
def monte(tmp_path):
    m = Monte(tmp_path)
    yield m
    m.arreter()


def test_changer_de_fournisseur_envoie_l_historique_a_plat_une_fois(monte):
    c = monte.historique.creer("4 Argon", "Min.").id
    monte.chat.envoyer(c, "Bonjour Gemini", "gemini", "4 Argon", "Min.")
    monte.chat.envoyer(c, "Et toi Ollama ?", "ollama", "llama3.2", None)
    premier = monte.ollama.recus[0]
    assert premier["adresse"] is None
    assert "[Conversation so far]" in premier["texte"] and "Bonjour Gemini" in premier["texte"]
    assert premier["texte"].endswith("Et toi Ollama ?")
    monte.chat.envoyer(c, "Encore", "ollama", "llama3.2", None)
    assert monte.ollama.recus[1] == {"adresse": "ollama:conv", "texte": "Encore", "modele": "llama3.2", "niveau": None}
    assert monte.historique.conversation(c).fournisseur == "ollama"
    assert [m.fournisseur for m in monte.historique.messages(c) if m.role == "gemini"] == ["gemini", "ollama", "ollama"]


def test_secours_quand_gemini_est_a_sa_limite(tmp_path):
    m = Monte(tmp_path, gemini=FauxPilote("gemini", LimiteGemini("Votre limite sera réinitialisée à 2:58 PM")))
    try:
        m.secours()
        c = m.historique.creer().id
        message = m.chat.envoyer(c, "Bonjour", "gemini", "4 Argon", "Min.")
        assert message["fournisseur"] == "ollama" and message["texte"].startswith("ollama")
        details = json.loads(message["details"])
        assert details["secours"]["de"] == "gemini" and details["secours"]["raison"] == "limite"
        assert m.historique.conversation(c).fournisseur == "ollama"
        assert m.ollama.recus[0]["modele"] == "llama3.2" and m.ollama.recus[0]["niveau"] is None
        assert m.fournisseurs.etats.lire("gemini") == {"etat": "limite", "detail": "jusqu'à 2:58 PM"}
        assert m.fournisseurs.etats.lire("ollama")["etat"] == "pret"
    finally:
        m.arreter()


def test_pas_de_secours_vers_le_meme_fournisseur(tmp_path):
    m = Monte(tmp_path, gemini=FauxPilote("gemini", LimiteGemini("plus tard")))
    try:
        m.secours("gemini", "3.8 Flash")
        c = m.historique.creer().id
        with pytest.raises(EchecEnvoi) as erreur:
            m.chat.envoyer(c, "Bonjour", "gemini")
        assert erreur.value.code == 502
        assert len(m.gemini.recus) == 1 and not m.ollama.recus
        assert [x.role for x in m.historique.messages(c)] == ["toi", "erreur"]
    finally:
        m.arreter()


def test_secours_en_panne_aussi(tmp_path):
    m = Monte(tmp_path, gemini=FauxPilote("gemini", LimiteGemini("plus tard")),
              ollama=FauxPilote("ollama", LimiteGemini("aussi")))
    try:
        m.secours()
        c = m.historique.creer().id
        with pytest.raises(EchecEnvoi) as erreur:
            m.chat.envoyer(c, "Bonjour", "gemini")
        assert "Gemini :" in erreur.value.message and "Secours (Ollama)" in erreur.value.message
    finally:
        m.arreter()


def test_un_modele_introuvable_ne_declenche_pas_le_secours(tmp_path):
    m = Monte(tmp_path, gemini=FauxPilote("gemini", ModeleIntrouvable("9 Zeta")))
    try:
        m.secours()
        with pytest.raises(EchecEnvoi):
            m.chat.envoyer(m.historique.creer().id, "Bonjour", "gemini", "9 Zeta")
        assert not m.ollama.recus
    finally:
        m.arreter()


def test_fournisseur_inactif_refuse(monte):
    with pytest.raises(EchecEnvoi) as erreur:
        monte.chat.envoyer(monte.historique.creer().id, "Bonjour", "mistral")
    assert erreur.value.code == 400


def test_reponse_de_gemini_sans_son_titre(monte):
    monte.gemini.reponse = "Gemini a dit\nBonjour !"
    message = monte.chat.envoyer(monte.historique.creer().id, "Salut", "gemini")
    assert message["texte"] == "Bonjour !"


# ---- routes de l'app ---------------------------------------------------------


@pytest.fixture
def client(monte):
    app = creer_app(monte.files[0], monte.historique, 2.0, lambda: True, PAR_DEFAUT, fournisseurs=monte.fournisseurs)
    return TestClient(app)


def test_routes_fournisseurs(client, monte):
    r = client.get("/api/fournisseurs").json()
    assert [f["id"] for f in r["actifs"]] == ["gemini", "ollama"]
    assert {f["id"] for f in r["tous"]} >= {"anthropic", "openai", "chatgpt", "claude_web", "ollama"}
    r = client.put("/api/fournisseurs/openai", json={"actif": True, "cle": "sk-secret-9876"}).json()
    openai = next(f for f in r["tous"] if f["id"] == "openai")
    assert openai["cle"] == "••••9876" and "sk-secret" not in json.dumps(r)
    assert client.put("/api/fournisseurs/inconnu", json={"actif": True}).status_code == 404
    assert client.put("/api/fournisseurs/gemini", json={"actif": False}).status_code == 422
    assert client.post("/api/fournisseurs/ollama/modeles").json() == {"modeles": ["llama3.2", "qwen3"]}
    r = client.put("/api/secours", json={"actif": True, "fournisseur": "ollama", "modele": "qwen3"}).json()
    assert r["secours"] == {"actif": True, "fournisseur": "ollama", "modele": "qwen3"}


def test_conversation_chez_un_autre_fournisseur(client, monte):
    c = client.post("/api/conversations", json={"fournisseur": "ollama", "modele": "llama3.2"}).json()
    assert c["fournisseur"] == "ollama"
    r = client.post(f"/api/conversations/{c['id']}/messages", json={"texte": "Salut", "fournisseur": "ollama",
                                                                     "modele": "llama3.2"})
    assert r.status_code == 200 and r.json()["message"]["fournisseur"] == "ollama"
    assert monte.ollama.recus[0]["texte"] == "Salut"  # même fournisseur : pas d'historique à plat
    assert client.post("/api/conversations", json={"fournisseur": "inconnu"}).status_code == 404


# ---- Cowork --------------------------------------------------------------------


def test_cowork_continue_chez_le_secours(tmp_path):
    from agent_first.cowork_service import ServiceCowork

    m = Monte(tmp_path, gemini=FauxPilote("gemini", LimiteGemini("Votre limite sera réinitialisée à 2:58 PM")),
              ollama=FauxPilote("ollama", reponse=FINI))
    try:
        m.secours()
        service = ServiceCowork(m.repartiteur, m.historique, fabrique_executeur, REGLAGES, fabrique_processus,
                                fournisseurs=m.fournisseurs)
        c = m.historique.creer(mode="cowork", dossier=str(tmp_path)).id
        service.demarrer(c, str(tmp_path), None, "Fais la tâche", "4 Argon", "Min.")
        evs = evenements(service, c)
        assert "secours" in types(evs) and fin(evs)["type"] == "termine"
        secours = next(e for e in evs if e["type"] == "secours")
        assert "Gemini à sa limite" in secours["corps"] and "Ollama · llama3.2" in secours["corps"]
        assert m.historique.conversation(c).fournisseur == "ollama"
        assert m.ollama.recus[0]["adresse"] is None and "Fais la tâche" in m.ollama.recus[0]["texte"]
    finally:
        m.arreter()


def test_cowork_chez_un_fournisseur_par_api(tmp_path):
    from agent_first.cowork_service import ServiceCowork

    m = Monte(tmp_path, ollama=FauxPilote("ollama", reponse=FINI))
    try:
        service = ServiceCowork(m.repartiteur, m.historique, fabrique_executeur, REGLAGES, fabrique_processus,
                                fournisseurs=m.fournisseurs)
        c = m.historique.creer("llama3.2", None, mode="cowork", dossier=str(tmp_path), fournisseur="ollama").id
        service.demarrer(c, str(tmp_path), None, "Fais la tâche", "llama3.2", None, fournisseur="ollama")
        assert fin(evenements(service, c))["type"] == "termine"
        assert not m.gemini.recus and m.ollama.recus[0]["modele"] == "llama3.2"
    finally:
        m.arreter()
