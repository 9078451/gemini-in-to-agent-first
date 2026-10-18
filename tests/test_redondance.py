"""Plusieurs assistants (Gemini, ChatGPT, Claude) et la redondance : un assistant saturé
ou à court de crédits passe la main au suivant, qui reprend la conversation."""
import json
import threading

import pytest
from fastapi.testclient import TestClient

from agent_first.api_reseau import creer_api_reseau, fournisseur_du_modele
from agent_first.cache_modes import CacheModes
from agent_first.cle_api import GardeCle
from agent_first.cowork_service import ServiceCowork
from agent_first.envoi import MAX_CARACTERES_RELAIS, Repartiteur, transcription
from agent_first.file_attente import FileAttente
from agent_first.fournisseurs import Fournisseur
from agent_first.historique import Historique, Message
from agent_first.mediatheque import Mediatheque
from agent_first.openai_compat import resoudre_modele_site
from agent_first.reglages_app import ReglagesApp
from agent_first.serveur import creer_app
from cowork.actions import Executeur
from cowork.boucle import Reglages
from cowork.processus import GestionnaireProcessus
from pilote.erreurs import LimiteAtteinte, MessageAbandonne
from pilote.modeles import Media, Modes, Option, ResultatGemini
from pilote.sites import SITES

NOMS = ["gemini", "chatgpt", "claude"]
MODES = {
    "gemini": Modes([Option("3.5 Flash", "", True), Option("3.1 Pro", "")], [Option("Min.", "", True)]),
    "chatgpt": Modes([Option("Auto", "", True), Option("Thinking", "")], []),
    "claude": Modes([Option("Sonnet 4.5", "", True), Option("Opus 4.1", "")], []),
}
REGLAGES = Reglages(max_tours=40, max_actions=10, echecs_max=3, taille_max=8000, taille_max_message=30000, relances_fin_max=2)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 32
SATURE = "You've reached your usage limit."


class Pilote:
    """Un faux assistant : répond « <nom> : réponse <n> », ou lève `erreur`."""

    def __init__(self, nom: str) -> None:
        self.nom = nom
        self.envois: list[dict] = []
        self.erreur: Exception | None = None
        self.medias: tuple[Media, ...] = ()
        self.attendre_arret = False

    def envoyer(self, adresse, texte, modele=None, niveau=None, delai=None, outil=None, pieces=(), au_fil=None,
                arret=None):
        self.envois.append({"adresse": adresse, "texte": texte, "modele": modele, "niveau": niveau, "outil": outil})
        if au_fil is not None:
            au_fil(f"{self.nom} : réponse")
        if self.attendre_arret:
            assert arret.wait(5)
            raise MessageAbandonne()
        if self.erreur is not None:
            raise self.erreur
        return ResultatGemini(reponse=f"{self.nom} : réponse {len(self.envois)}", adresse=f"https://{self.nom}.example/c/1",
                              modele=modele, medias=self.medias)

    def est_connecte(self):
        return True

    def lister_modes(self):
        return MODES[self.nom]


@pytest.fixture
def monte(tmp_path):
    pilotes = {n: Pilote(n) for n in NOMS}
    files = {n: FileAttente(lambda n=n: pilotes[n], nom=f"file-{n}") for n in NOMS}
    for file in files.values():
        file.demarrer()
    fournisseurs = {
        n: Fournisseur(SITES[n], files[n], files[n], CacheModes(files[n], lambda: True, MODES[n])) for n in NOMS
    }
    historique = Historique(tmp_path / "historique.db")
    reglages = ReglagesApp(tmp_path / "reglages.json", NOMS)
    delais = {"image": 5.0, "video": 5.0, "musique": 5.0}
    repartiteur = Repartiteur(fournisseurs, historique, reglages, 5.0, delais, 1.0)
    mediatheque = Mediatheque(tmp_path / "medias")
    app = creer_app(files["gemini"], historique, 5.0, lambda: True, MODES["gemini"], mediatheque=mediatheque,
                    delais_media=delais, attente_file=1.0, cache_modes=fournisseurs["gemini"].modes,
                    repartiteur=repartiteur, reglages=reglages)
    service = ServiceCowork(
        files["gemini"], historique,
        lambda dossier, processus, arret: Executeur(dossier, 5, 8000, lancer=lambda *a, **k: (0, ""), processus=processus, arret=arret),
        REGLAGES,
        lambda dossier, au_changement: GestionnaireProcessus(dossier, 3, 0.3, 8000, au_changement=au_changement),
        files={n: files[n] for n in NOMS},
    )
    garde = GardeCle(tmp_path / "cle.txt")
    api = creer_api_reseau(files["gemini"], historique, service, garde, fournisseurs["gemini"].modes, 5.0,
                           mediatheque=mediatheque, delais_media=delais, attente_file=1.0, repartiteur=repartiteur)

    class Monte:
        pass

    m = Monte()
    m.client, m.pilotes, m.historique, m.reglages, m.repartiteur = TestClient(app), pilotes, historique, reglages, repartiteur
    m.api = TestClient(api, headers={"Authorization": f"Bearer {garde.cle}"})
    m.dossier = tmp_path
    yield m
    for file in files.values():
        file.arreter()


def nouvelle(m, **choix) -> str:
    return m.client.post("/api/conversations", json=choix).json()["id"]


def envoyer(m, conversation, texte, **options):
    return m.client.post(f"/api/conversations/{conversation}/messages", json={"texte": texte, **options})


# ---- choisir l'assistant ------------------------------------------------


def test_le_nom_du_modele_chez_l_assistant():
    noms = ["Sonnet 4.5", "Opus 4.1", "Haiku 4.5"]
    assert resoudre_modele_site("claude-opus-4-1", noms, ("claude",)) == "Opus 4.1"
    assert resoudre_modele_site("claude-sonnet-4-5-20250929", noms, ("claude",)) == "Sonnet 4.5"
    assert resoudre_modele_site("haiku", noms) == "Haiku 4.5"
    assert resoudre_modele_site("claude-4-5", noms, ("claude",)) is None  # Sonnet ou Haiku ?
    assert resoudre_modele_site("gpt-5-thinking", ["Auto", "Instant", "Thinking"], ("gpt",)) == "Thinking"
    assert resoudre_modele_site("gpt-4o", ["Auto", "Instant", "Thinking"], ("gpt",)) is None
    assert resoudre_modele_site("auto", ["Auto", "Instant"]) == "Auto"


def test_le_nom_du_modele_designe_l_assistant():
    actifs = ["gemini", "chatgpt", "claude", "mistral", "deepseek", "grok"]
    assert fournisseur_du_modele("gpt-5", actifs) == "chatgpt"
    assert fournisseur_du_modele("o3-mini", actifs) == "chatgpt"
    assert fournisseur_du_modele("openai/gpt-4o", actifs) == "chatgpt"
    assert fournisseur_du_modele("chatgpt/Thinking", actifs) == "chatgpt"
    assert fournisseur_du_modele("claude-sonnet-4-5", actifs) == "claude"
    assert fournisseur_du_modele("Claude", actifs) == "claude"
    assert fournisseur_du_modele("mistral-large-latest", actifs) == "mistral"
    assert fournisseur_du_modele("deepseek-chat", actifs) == "deepseek"
    assert fournisseur_du_modele("grok-4", actifs) == "grok"
    assert fournisseur_du_modele("gemini-2.5-pro", actifs) == "gemini"
    assert fournisseur_du_modele("3.1 Pro", actifs) is None  # un modèle de Gemini, sans préfixe
    assert fournisseur_du_modele("gpt-5", ["gemini"]) is None  # ChatGPT désactivé : Gemini répond
    assert fournisseur_du_modele("o3mini", actifs) is None


def test_les_assistants_et_leurs_modeles(monte):
    decrits = monte.client.get("/api/fournisseurs").json()
    assert [d["nom"] for d in decrits] == NOMS
    assert decrits[1]["libelle"] == "ChatGPT" and decrits[1]["outils"] == ["image"]
    assert decrits[2]["outils"] == [] and [o["nom"] for o in decrits[2]["modeles"]] == ["Sonnet 4.5", "Opus 4.1"]
    assert "video" in decrits[0]["outils"]
    assert monte.client.get("/api/modeles", params={"fournisseur": "chatgpt"}).json()["modeles"][1]["nom"] == "Thinking"
    assert monte.client.get("/api/modeles", params={"fournisseur": "inconnu"}).status_code == 404
    assert monte.client.get("/api/etat").json()["fournisseurs"] == {"gemini": True, "chatgpt": True, "claude": True}


def test_une_conversation_avec_chatgpt(monte):
    conversation = nouvelle(monte, fournisseur="chatgpt")
    r = envoyer(monte, conversation, "Bonjour", modele="Thinking")
    assert r.status_code == 200 and r.json()["fournisseur"] == "chatgpt"
    assert r.json()["message"]["texte"] == "chatgpt : réponse 1"
    assert monte.pilotes["chatgpt"].envois == [{"adresse": None, "texte": "Bonjour", "modele": "Thinking", "niveau": None,
                                                "outil": None}]
    assert not monte.pilotes["gemini"].envois
    assert json.loads(r.json()["message"]["details"])["fournisseur"] == "chatgpt"
    envoyer(monte, conversation, "Et après ?")
    assert monte.pilotes["chatgpt"].envois[1]["adresse"] == "https://chatgpt.example/c/1"
    assert monte.pilotes["chatgpt"].envois[1]["texte"] == "Et après ?"  # il a vu la conversation : pas de transcription
    assert monte.client.post("/api/conversations", json={"fournisseur": "inconnu"}).status_code == 422


def test_claude_ne_cree_pas_d_image(monte):
    conversation = nouvelle(monte, fournisseur="claude")
    r = envoyer(monte, conversation, "un chat", outil="image")
    assert r.status_code == 422 and "Claude" in r.json()["erreur"]


def test_changer_d_assistant_en_cours_de_conversation(monte):
    conversation = nouvelle(monte)
    envoyer(monte, conversation, "Je m'appelle Lou")
    changee = monte.client.post(f"/api/conversations/{conversation}/fournisseur", json={"fournisseur": "claude"}).json()
    assert changee["fournisseur"] == "claude" and changee["adresse"] is None
    envoyer(monte, conversation, "Comment je m'appelle ?")
    [envoi] = monte.pilotes["claude"].envois
    assert envoi["adresse"] is None
    assert "User: Je m'appelle Lou" in envoi["texte"] and "Assistant: gemini : réponse 1" in envoi["texte"]
    assert envoi["texte"].endswith("Comment je m'appelle ?")
    inconnu = monte.client.post(f"/api/conversations/{conversation}/fournisseur", json={"fournisseur": "x"})
    assert inconnu.status_code == 422


# ---- sans redondance : on propose, l'utilisateur choisit -------------------


def test_sans_redondance_l_erreur_propose_les_autres_assistants(monte):
    conversation = nouvelle(monte)
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    r = envoyer(monte, conversation, "Bonjour")
    assert r.status_code == 429 and "redondance" in r.json()["erreur"]
    assert r.json()["autres"] == ["chatgpt", "claude"]
    assert not monte.pilotes["chatgpt"].envois and not monte.pilotes["claude"].envois
    assert monte.historique.conversation(conversation).fournisseur == "gemini"


def test_une_erreur_qui_n_est_pas_celle_de_l_assistant_ne_propose_rien(monte):
    conversation = nouvelle(monte)
    monte.pilotes["gemini"].erreur = RuntimeError("panne")
    r = envoyer(monte, conversation, "Bonjour", redondance=True)
    assert r.status_code == 500 and "autres" not in r.json()
    assert not monte.pilotes["chatgpt"].envois


# ---- avec redondance : un autre assistant prend le relais -----------------


def test_avec_la_redondance_chatgpt_reprend_la_conversation(monte):
    conversation = nouvelle(monte)
    assert envoyer(monte, conversation, "Je m'appelle Lou").status_code == 200
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    r = envoyer(monte, conversation, "Comment je m'appelle ?", redondance=True)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["fournisseur"] == "chatgpt" and corps["message"]["texte"] == "chatgpt : réponse 1"
    assert [(n["de"], n["vers"]) for n in corps["relais"]] == [("Gemini", "ChatGPT")]
    assert "limite" in corps["relais"][0]["raison"]
    [envoi] = monte.pilotes["chatgpt"].envois
    assert envoi["adresse"] is None and "User: Je m'appelle Lou" in envoi["texte"]
    assert envoi["texte"].endswith("Comment je m'appelle ?")
    # La conversation continue chez ChatGPT, sans repasser par Gemini
    assert monte.historique.conversation(conversation).fournisseur == "chatgpt"
    roles = [m.role for m in monte.historique.messages(conversation)]
    assert roles == ["toi", "gemini", "toi", "relais", "gemini"]
    envoyer(monte, conversation, "Merci")
    assert monte.pilotes["chatgpt"].envois[1] == {"adresse": "https://chatgpt.example/c/1", "texte": "Merci",
                                                  "modele": None, "niveau": None, "outil": None}
    assert len(monte.pilotes["gemini"].envois) == 2


def test_la_redondance_suit_l_ordre_des_reglages(monte):
    lus = monte.client.post("/api/reglages", json={"redondance": True, "ordre": ["claude", "x", "gemini"]}).json()
    assert lus == {"redondance": True, "ordre": ["claude", "gemini", "chatgpt"]}  # inconnus retirés, oubliés à la fin
    assert monte.client.get("/api/reglages").json() == lus
    assert json.loads((monte.dossier / "reglages.json").read_text(encoding="utf-8")) == lus
    conversation = nouvelle(monte)
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    monte.pilotes["claude"].erreur = LimiteAtteinte("Claude", "Claude is at capacity")
    r = envoyer(monte, conversation, "Bonjour")  # sans `redondance` : le réglage de l'app
    assert r.status_code == 200 and r.json()["fournisseur"] == "chatgpt"
    assert [(n["de"], n["vers"]) for n in r.json()["relais"]] == [("Gemini", "Claude"), ("Claude", "ChatGPT")]
    # Le message peut refuser la redondance
    autre = nouvelle(monte)
    assert envoyer(monte, autre, "Bonjour", redondance=False).status_code == 429


def test_tous_satures_l_erreur_du_dernier(monte):
    conversation = nouvelle(monte)
    for nom in NOMS:
        monte.pilotes[nom].erreur = LimiteAtteinte(SITES[nom].libelle, SATURE)
    r = envoyer(monte, conversation, "Bonjour", redondance=True)
    assert r.status_code == 429 and "Claude" in r.json()["erreur"]
    assert r.json().get("autres") is None  # tous essayés


def test_une_image_ne_passe_qu_aux_assistants_qui_savent_la_creer(monte):
    monte.reglages.ecrire(ordre=["gemini", "claude", "chatgpt"])
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    monte.pilotes["chatgpt"].medias = (Media("image", "image/png", PNG, "un chat"),)
    conversation = nouvelle(monte)
    r = envoyer(monte, conversation, "un chat roux", outil="image", redondance=True)
    assert r.status_code == 200 and r.json()["fournisseur"] == "chatgpt"
    assert not monte.pilotes["claude"].envois  # Claude ne crée pas d'image : sauté
    assert monte.pilotes["chatgpt"].envois[0]["outil"] == "image"
    assert r.json()["message"]["medias"][0]["type"] == "image"
    # Une vidéo : personne d'autre ne sait la faire
    video = nouvelle(monte)
    r = envoyer(monte, video, "un chat qui court", outil="video", redondance=True)
    assert r.status_code == 429 and not r.json().get("relais")


def test_en_direct_le_relais_s_annonce_puis_l_autre_ecrit(monte):
    conversation = nouvelle(monte)
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    r = monte.client.post(f"/api/conversations/{conversation}/messages", params={"direct": True},
                          json={"texte": "Bonjour", "redondance": True})
    lignes = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert [l["type"] for l in lignes] == ["texte", "relais", "texte", "fin"]
    assert lignes[0]["fournisseur"] == "gemini"
    assert lignes[2] == {"type": "texte", "texte": "chatgpt : réponse", "fournisseur": "chatgpt"}
    assert lignes[1]["vers"] == "ChatGPT" and lignes[3]["fournisseur"] == "chatgpt"
    assert lignes[3]["message"]["texte"] == "chatgpt : réponse 1"


def test_en_direct_sans_redondance_l_erreur_propose_les_autres(monte):
    conversation = nouvelle(monte)
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    r = monte.client.post(f"/api/conversations/{conversation}/messages", params={"direct": True}, json={"texte": "Bonjour"})
    derniere = json.loads(r.text.splitlines()[-1])
    assert derniere["type"] == "erreur" and derniere["code"] == 429 and derniere["autres"] == ["chatgpt", "claude"]


def test_arreter_ne_passe_pas_la_main(monte):
    conversation = nouvelle(monte)
    monte.pilotes["gemini"].attendre_arret = True
    tentatives = []
    suivi = threading.Event()

    def suivre(tentative):
        tentatives.append(tentative)
        suivi.set()

    def arreter():
        assert suivi.wait(5)
        while not monte.pilotes["gemini"].envois:
            threading.Event().wait(0.01)
        tentatives[0].arreter()

    threading.Thread(target=arreter).start()
    with pytest.raises(MessageAbandonne):
        monte.repartiteur.envoyer(conversation, lambda nom, adresse: "Bonjour", redondance=True, suivre=suivre)
    assert not monte.pilotes["chatgpt"].envois


# ---- la transcription ---------------------------------------------------


def message(role, texte):
    return Message(1, "c", role, texte, None, None, None, None, None, "")


def test_la_transcription_garde_les_echanges_les_plus_recents():
    precedents = [message("toi", "a" * 6000), message("gemini", "b" * 6000), message("erreur", "ignorée"),
                  message("relais", "Gemini → ChatGPT"), message("toi", "c" * 6000), message("gemini", "d" * 3000)]
    texte = transcription(precedents, "Et maintenant ?")
    assert "a" * 6000 not in texte and "User: " + "c" * 6000 in texte and "Assistant: " + "d" * 3000 in texte
    assert "ignorée" not in texte and "→" not in texte
    assert texte.endswith("Et maintenant ?") and len(texte) < MAX_CARACTERES_RELAIS + 500
    assert transcription([], "Bonjour") == "Bonjour"


# ---- l'API réseau --------------------------------------------------------


def test_api_le_modele_choisit_l_assistant(monte):
    r = monte.api.post("/v1/chat/completions", json={"model": "chatgpt/Thinking", "messages": [{"role": "user", "content": "Bonjour"}]})
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "chatgpt/Thinking" and r.json()["provider"] == "chatgpt"
    assert r.json()["choices"][0]["message"]["content"] == "chatgpt : réponse 1"
    assert monte.pilotes["chatgpt"].envois[0]["modele"] == "Thinking"
    r = monte.api.post("/v1/chat/completions", json={"model": "claude-opus", "messages": [{"role": "user", "content": "Salut"}]})
    assert r.json()["model"] == "claude/Opus 4.1" and monte.pilotes["claude"].envois[0]["modele"] == "Opus 4.1"
    r = monte.api.post("/v1/chat/completions", json={"provider": "claude", "messages": [{"role": "user", "content": "Salut"}]})
    assert r.json()["model"] == "claude" and len(monte.pilotes["claude"].envois) == 2
    r = monte.api.post("/v1/chat/completions", json={"model": "3.1 Pro", "messages": [{"role": "user", "content": "Salut"}]})
    assert r.json()["model"] == "3.1 Pro" and monte.pilotes["gemini"].envois[0]["modele"] == "3.1 Pro"
    r = monte.api.post("/v1/chat/completions", json={"provider": "x", "messages": [{"role": "user", "content": "Salut"}]})
    assert r.status_code == 400 and "provider" in r.json()["error"]["message"]


def test_api_liste_les_modeles_de_chaque_assistant(monte):
    ids = [m["id"] for m in monte.api.get("/v1/models").json()["data"]]
    assert ids == ["3.5 Flash", "3.1 Pro", "chatgpt/Auto", "chatgpt/Thinking", "chatgpt", "claude/Sonnet 4.5",
                   "claude/Opus 4.1", "claude", "agent-first"]
    assert monte.api.get("/v1/models/chatgpt/Thinking").json()["owned_by"] == "chatgpt"


def test_api_redondance(monte):
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    demande = {"messages": [{"role": "user", "content": "Bonjour"}]}
    r = monte.api.post("/v1/chat/completions", json=demande)
    assert r.status_code == 429 and r.json()["error"]["type"] == "rate_limit_error"
    r = monte.api.post("/v1/chat/completions", json={**demande, "redundancy": True})
    assert r.status_code == 200 and r.json()["provider"] == "chatgpt"
    conversation = monte.historique.lister()[0]
    assert conversation.fournisseur == "chatgpt"
    assert [m.role for m in monte.historique.messages(conversation.id)] == ["toi", "relais", "gemini"]
    # La suite de la conversation reste chez ChatGPT
    suite = {"redundancy": True, "messages": demande["messages"] + [r.json()["choices"][0]["message"],
                                                                    {"role": "user", "content": "Et ensuite ?"}]}
    r = monte.api.post("/v1/chat/completions", json=suite)
    assert r.status_code == 200 and monte.pilotes["chatgpt"].envois[-1]["texte"] == "Et ensuite ?"
    assert monte.pilotes["chatgpt"].envois[-1]["adresse"] == "https://chatgpt.example/c/1"


def test_api_flux_avec_relais(monte):
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    r = monte.api.post("/v1/chat/completions", json={"stream": True, "redundancy": True,
                                                       "messages": [{"role": "user", "content": "Bonjour"}]})
    morceaux = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: {")]
    texte = "".join(m["choices"][0]["delta"].get("content", "") for m in morceaux)
    assert texte == "gemini : réponse\n\n— ChatGPT prend le relais —\n\nchatgpt : réponse 1"
    assert [m.get("provider") for m in morceaux] == [None, "gemini", "chatgpt", "chatgpt", "chatgpt", "chatgpt"]
    assert morceaux[-1]["model"] == "chatgpt"


def test_api_images_selon_l_assistant(monte):
    monte.pilotes["chatgpt"].medias = (Media("image", "image/png", PNG, "un chat"),)
    r = monte.api.post("/v1/images/generations", json={"prompt": "un chat", "model": "gpt-image-1"})
    assert r.status_code == 200, r.text
    assert monte.pilotes["chatgpt"].envois[0]["outil"] == "image" and not monte.pilotes["gemini"].envois
    r = monte.api.post("/v1/images/generations", json={"prompt": "un chat", "provider": "claude"})
    assert r.status_code == 400 and "Claude cannot create image" in r.json()["error"]["message"]
    r = monte.api.post("/v1/media/generations", json={"type": "video", "prompt": "un chat", "model": "gpt-5"})
    assert r.status_code == 400 and "Gemini" in r.json()["error"]["message"]


def test_api_image_avec_redondance(monte):
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    monte.pilotes["chatgpt"].medias = (Media("image", "image/png", PNG, "un chat"),)
    r = monte.api.post("/v1/media/generations", json={"type": "image", "prompt": "un chat", "redundancy": True})
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "chatgpt" and r.json()["data"][0]["type"] == "image"
    assert not monte.pilotes["claude"].envois


def test_api_cowork_avec_un_autre_assistant(monte):
    r = monte.api.post("/v1/cowork", json={"folder": str(monte.dossier), "request": "range", "model": "claude"})
    assert r.status_code == 200, r.text
    assert monte.historique.conversation(r.json()["id"]).fournisseur == "claude"
    fin = threading.Event()
    for _ in range(200):
        if monte.pilotes["claude"].envois:
            break
        fin.wait(0.02)
    assert monte.pilotes["claude"].envois and not monte.pilotes["gemini"].envois


def test_l_export_nomme_l_assistant_et_le_relais(monte):
    import io
    import zipfile

    conversation = nouvelle(monte)
    envoyer(monte, conversation, "Bonjour")
    monte.pilotes["gemini"].erreur = LimiteAtteinte("Gemini", SATURE)
    envoyer(monte, conversation, "Encore", redondance=True)
    archive = zipfile.ZipFile(io.BytesIO(monte.client.get(f"/api/conversations/{conversation}/export").content))
    texte = archive.read("conversation.md").decode("utf-8")
    assert "### Gemini ·" in texte and "### ChatGPT ·" in texte and "_Relais : Gemini → ChatGPT_" in texte
