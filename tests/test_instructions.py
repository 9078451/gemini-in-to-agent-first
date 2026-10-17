from pathlib import Path

from cowork import instructions
from cowork.catalogue import CATALOGUE
from cowork.instructions import arborescence, cadre


def un_cadre(**options):
    reglages = dict(contenu="a.txt", entrees="1", processus="", derniere_tache="", reponse=False, max_actions=10)
    reglages.update(options)
    return cadre(Path("C:/travail"), "crée a.txt", **reglages)


def test_cadre_contient_role_actions_dossier_demande():
    texte = un_cadre()
    assert texte.startswith("[AGENT FIRST · COWORK]")
    for nom in CATALOGUE:
        assert f'"action": "{nom}"' in texte
    assert str(Path("C:/travail")) in texte
    assert '"""\ncrée a.txt\n"""' in texte
    assert "Never tell the user to run something" in texte
    assert "in French" in texte
    assert "Reply now with your first actions." in texte


def test_cadre_regle_echappement():
    # Sans cette règle, Gemini laissait des guillemets non échappés dans le code (JSON invalide).
    texte = un_cadre()
    assert '\\"' in texte and "\\n" in texte


def test_cadre_max_actions():
    assert "Up to 7 per message" in un_cadre(max_actions=7)


def test_cadre_reponse_a_une_question():
    texte = un_cadre(reponse=True)
    assert "USER ANSWER TO YOUR QUESTION:" in texte and "USER REQUEST:" not in texte


def test_cadre_dit_que_le_dossier_est_borne():
    assert "File actions only work inside the working folder" in un_cadre()


def test_cadre_contexte_vide_et_rempli():
    vide = un_cadre()
    assert "RUNNING PROCESSES: none" in vide and "LAST TASK: none" in vide
    rempli = un_cadre(processus="#1 python server.py (since 10:52)", derniere_tache="done: page créée")
    assert "RUNNING PROCESSES: #1 python server.py (since 10:52)" in rempli
    assert "LAST TASK: done: page créée" in rempli
    assert "FOLDER CONTENT (1 entry):\na.txt" in rempli


def test_cadre_compte_les_entrees():
    assert "FOLDER CONTENT (37 entries):\na.txt" in un_cadre(entrees="37")
    assert "FOLDER CONTENT (10150+ entries):\na.txt" in un_cadre(entrees="10150+")


def test_arborescence(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x")
    (tmp_path / "c.py").write_text("x")
    for ignore in (".git", "node_modules", "__pycache__", ".venv", "venv"):
        (tmp_path / ignore).mkdir()
        (tmp_path / ignore / "x").write_text("x")
    assert arborescence(tmp_path, 150) == ("a/\n  b.txt\nc.py", "3")


def test_arborescence_limite(tmp_path):
    for i in range(200):
        (tmp_path / f"f{i:03}.txt").write_text("x")
    texte, entrees = arborescence(tmp_path, 150)
    assert len(texte.splitlines()) == 151 and texte.endswith("… (50 more)") and entrees == "200"


def test_arborescence_compte_arrete(tmp_path, monkeypatch):
    monkeypatch.setattr(instructions, "_COMPTE_MAX", 5)
    for i in range(20):
        (tmp_path / f"f{i:02}.txt").write_text("x")
    texte, entrees = arborescence(tmp_path, 10)
    assert texte.endswith("… (5+ more)") and entrees == "15+"


def test_arborescence_vide(tmp_path):
    assert arborescence(tmp_path, 150) == ("(empty)", "0")


def test_arborescence_boucle_de_jonction(tmp_path):
    import pytest

    _winapi = pytest.importorskip("_winapi")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.txt").write_text("x")
    _winapi.CreateJunction(str(tmp_path / "a"), str(tmp_path / "a" / "boucle"))
    texte, _ = arborescence(tmp_path, 150)  # ne doit pas finir en RecursionError
    assert texte.startswith("a/\n  boucle/")


def test_cadre_pousse_a_tout_faire_en_un_message():
    # Mesuré en essai réel : 2 allers-retours (78 s) pour créer, lancer et vérifier un serveur.
    texte = un_cadre()
    assert "Work in batches" in texte and "create + start + visit" in texte
    assert "Stop a batch only where you need a result you have not seen" in texte
    assert "a done at the end only counts if everything before it succeeded" in texte
    assert texte.endswith("If the request is simple, do it all in this first message.")


def test_cadre_avec_le_resume_de_la_conversation():
    texte = un_cadre(conversation='- "crée a.txt" → done — created: a.txt')
    assert "EARLIER IN THIS CONVERSATION" in texte and '- "crée a.txt" → done — created: a.txt' in texte
    assert "EARLIER IN THIS CONVERSATION" not in un_cadre()
