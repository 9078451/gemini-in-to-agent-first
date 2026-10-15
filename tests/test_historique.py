from datetime import datetime, timedelta

import pytest

from agent_first.historique import ConversationInconnue, Historique, titre_depuis


class Horloge:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 15, 12, 0, 0)

    def __call__(self) -> datetime:
        return self.t

    def avancer(self, **duree) -> None:
        self.t += timedelta(**duree)


@pytest.fixture
def horloge():
    return Horloge()


@pytest.fixture
def historique(tmp_path, horloge):
    return Historique(tmp_path / "historique.db", horloge)


def test_titre_depuis_premier_message(historique):
    c = historique.creer("3.1 Pro", "Max.")
    historique.ajouter_message(c.id, "toi", "Écris un texte\nsur les phares")
    historique.ajouter_message(c.id, "toi", "Autre chose")
    assert historique.conversation(c.id).titre == "Écris un texte sur les phares"


def test_titre_long_coupe():
    titre = titre_depuis("mot " * 40)
    assert len(titre) == 60
    assert titre.endswith("…")


def test_messages_dans_l_ordre(historique):
    c = historique.creer()
    historique.ajouter_message(c.id, "toi", "Bonjour", modele="4 Argon", niveau="Min.")
    historique.ajouter_message(c.id, "gemini", "Salut", html="<p>Salut</p>", modele="4 Argon", niveau="Min.", duree=3.2)
    messages = historique.messages(c.id)
    assert [(m.role, m.texte) for m in messages] == [("toi", "Bonjour"), ("gemini", "Salut")]
    assert (messages[1].html, messages[1].duree) == ("<p>Salut</p>", 3.2)
    assert (historique.conversation(c.id).modele, historique.conversation(c.id).niveau) == ("4 Argon", "Min.")


def test_garde_tout_apres_redemarrage(tmp_path, horloge):
    fichier = tmp_path / "donnees" / "historique.db"
    h = Historique(fichier, horloge)
    c = h.creer()
    h.ajouter_message(c.id, "toi", "Bonjour")
    h.enregistrer_adresse(c.id, "https://gemini.google.com/app/abc")
    relu = Historique(fichier, horloge)
    assert relu.conversation(c.id).adresse == "https://gemini.google.com/app/abc"
    assert [m.texte for m in relu.messages(c.id)] == ["Bonjour"]


def test_liste_recente_d_abord_sans_conversations_vides(historique, horloge):
    a = historique.creer()
    historique.ajouter_message(a.id, "toi", "Premier")
    horloge.avancer(minutes=5)
    b = historique.creer()
    historique.ajouter_message(b.id, "toi", "Second")
    historique.creer()
    conversations = historique.lister()
    assert [c.titre for c in conversations] == ["Second", "Premier"]
    assert conversations[0].nb_messages == 1


def test_recherche_dans_titres_et_messages(historique):
    a = historique.creer()
    historique.ajouter_message(a.id, "toi", "Les phares")
    b = historique.creer()
    historique.ajouter_message(b.id, "toi", "Code Python")
    historique.ajouter_message(b.id, "gemini", "Voici une boucle for")
    assert [c.titre for c in historique.lister("phares")] == ["Les phares"]
    assert [c.titre for c in historique.lister("boucle")] == ["Code Python"]


def test_recherche_sans_jokers(historique):
    c = historique.creer()
    historique.ajouter_message(c.id, "toi", "Bonjour")
    assert historique.lister("%") == []
    assert historique.lister("_") == []


def test_periode(historique, horloge):
    ancienne = historique.creer()
    historique.ajouter_message(ancienne.id, "toi", "Il y a longtemps")
    horloge.avancer(days=10)
    recente = historique.creer()
    historique.ajouter_message(recente.id, "toi", "Récente")
    assert [c.titre for c in historique.lister(periode="7j")] == ["Récente"]
    assert len(historique.lister(periode="30j")) == 2


def test_supprimer(historique):
    c = historique.creer()
    historique.ajouter_message(c.id, "toi", "Bonjour")
    historique.supprimer(c.id)
    assert historique.lister() == []
    with pytest.raises(ConversationInconnue):
        historique.messages(c.id)


def test_conversation_inconnue(historique):
    with pytest.raises(ConversationInconnue):
        historique.conversation("nexistepas")
    with pytest.raises(ConversationInconnue):
        historique.ajouter_message("nexistepas", "toi", "x")


def test_statistiques(historique):
    a = historique.creer()
    historique.ajouter_message(a.id, "toi", "Q1")
    historique.ajouter_message(a.id, "gemini", "R1", modele="3.1 Pro", duree=10.0)
    historique.ajouter_message(a.id, "toi", "Q2")
    historique.ajouter_message(a.id, "gemini", "R2", modele="3.1 Pro", duree=20.0)
    b = historique.creer()
    historique.ajouter_message(b.id, "toi", "Q3")
    historique.ajouter_message(b.id, "gemini", "R3", modele="4 Argon", duree=6.0)
    assert historique.statistiques("7j") == {
        "conversations": 2, "messages": 3, "modele_favori": "3.1 Pro", "temps_moyen": 12.0,
    }


def test_statistiques_vides(historique):
    assert historique.statistiques("tout") == {
        "conversations": 0, "messages": 0, "modele_favori": None, "temps_moyen": None,
    }


def test_base_corrompue_mise_de_cote(tmp_path, horloge):
    fichier = tmp_path / "historique.db"
    fichier.write_bytes(b"ceci n'est pas une base SQLite " * 10)
    h = Historique(fichier, horloge)
    c = h.creer()
    h.ajouter_message(c.id, "toi", "Bonjour")
    assert len(h.lister()) == 1
    assert (tmp_path / "historique.corrompu.db").exists()
