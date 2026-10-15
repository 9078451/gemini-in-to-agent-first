import pytest

from agent_first.conversations import ConversationInconnue, MemoireConversations


def test_nouvelle_conversation_sans_adresse(tmp_path):
    memoire = MemoireConversations(tmp_path / "conv.json")
    identifiant = memoire.creer()
    assert memoire.adresse(identifiant) is None


def test_identifiants_differents(tmp_path):
    memoire = MemoireConversations(tmp_path / "conv.json")
    assert memoire.creer() != memoire.creer()


def test_adresse_gardee_apres_redemarrage(tmp_path):
    fichier = tmp_path / "donnees" / "conv.json"
    memoire = MemoireConversations(fichier)
    identifiant = memoire.creer()
    memoire.enregistrer(identifiant, "https://gemini.google.com/app/abc")
    assert MemoireConversations(fichier).adresse(identifiant) == "https://gemini.google.com/app/abc"


def test_conversation_inconnue(tmp_path):
    memoire = MemoireConversations(tmp_path / "conv.json")
    with pytest.raises(ConversationInconnue):
        memoire.adresse("nexistepas")
    with pytest.raises(ConversationInconnue):
        memoire.enregistrer("nexistepas", "https://gemini.google.com/app/abc")


def test_fichier_corrompu_repart_de_zero(tmp_path):
    fichier = tmp_path / "conv.json"
    fichier.write_text("{ pas du json", encoding="utf-8")
    memoire = MemoireConversations(fichier)
    identifiant = memoire.creer()
    assert memoire.adresse(identifiant) is None


def test_fichier_corrompu_mis_de_cote(tmp_path):
    fichier = tmp_path / "conv.json"
    fichier.write_text("[1, 2]", encoding="utf-8")
    MemoireConversations(fichier)
    assert (tmp_path / "conv.corrompu.json").read_text(encoding="utf-8") == "[1, 2]"
