from pathlib import Path

from cowork.catalogue import CATALOGUE
from cowork.instructions import arborescence, cadre


def un_cadre(**options):
    reglages = dict(contenu="a.txt", processus="", derniere_tache="", reponse=False, max_actions=10)
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
    assert texte.endswith("Reply now with your first actions.")


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
    assert "FOLDER CONTENT:\na.txt" in rempli


def test_arborescence(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x")
    (tmp_path / "c.py").write_text("x")
    for ignore in (".git", "node_modules", "__pycache__", ".venv", "venv"):
        (tmp_path / ignore).mkdir()
        (tmp_path / ignore / "x").write_text("x")
    assert arborescence(tmp_path, 150) == "a/\n  b.txt\nc.py"


def test_arborescence_limite(tmp_path):
    for i in range(200):
        (tmp_path / f"f{i:03}.txt").write_text("x")
    texte = arborescence(tmp_path, 150)
    assert len(texte.splitlines()) == 151 and texte.endswith("… (50 more)")


def test_arborescence_vide(tmp_path):
    assert arborescence(tmp_path, 150) == "(empty)"
