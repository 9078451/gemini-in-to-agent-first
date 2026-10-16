import subprocess

import pytest

from cowork.actions import Executeur
from cowork.format import Action


@pytest.fixture
def appels():
    return []


@pytest.fixture
def ex(tmp_path, appels):
    def faux_lancer(texte, dossier, delai):
        appels.append((texte, dossier, delai))
        return (0, "sortie simulée")

    return Executeur(tmp_path, 5, 8000, lancer=faux_lancer)


def test_creer_puis_lire(ex, tmp_path):
    assert ex.executer(Action("creer", {"chemin": "a.txt", "contenu": "bonjour"})).ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "bonjour"
    assert ex.executer(Action("lire", {"chemin": "a.txt"})).corps == "bonjour"


def test_lister(ex, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert "a.txt" in ex.executer(Action("lister", {"chemin": "."})).corps


def test_modifier_fait_un_diff(ex, tmp_path):
    (tmp_path / "a.txt").write_text("rouge", encoding="utf-8")
    r = ex.executer(Action("modifier", {"chemin": "a.txt", "avant": "rouge", "apres": "vert"}))
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "vert"
    assert "-rouge" in r.diff and "+vert" in r.diff


def test_chercher(ex, tmp_path):
    (tmp_path / "a.txt").write_text("alpha\nbeta", encoding="utf-8")
    assert "beta" in ex.executer(Action("chercher", {"motif": "beta"})).corps


def test_supprimer(ex, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert ex.executer(Action("supprimer", {"chemin": "a.txt"})).ok
    assert not (tmp_path / "a.txt").exists()


def test_resoudre_refuse_hors_dossier(ex):
    for chemin in ("../secret.txt", "C:/Windows/x.txt"):
        r = ex.executer(Action("lire", {"chemin": chemin}))
        assert r.ok is False and "hors du dossier" in r.corps


def test_commande_passe_par_lancer(ex, appels, tmp_path):
    r = ex.executer(Action("commande", {"texte": "echo bonjour"}))
    assert r.ok and r.corps == "sortie simulée"
    assert appels == [("echo bonjour", tmp_path, 5)]


def test_commande_trop_longue(tmp_path):
    def lent(*_):
        raise subprocess.TimeoutExpired("ps", 1)

    ex = Executeur(tmp_path, 1, 8000, lancer=lent)
    r = ex.executer(Action("commande", {"texte": "sleep"}))
    assert r.ok is False and "trop longue" in r.corps


def test_sortie_coupee(tmp_path):
    ex = Executeur(tmp_path, 5, 10, lancer=lambda *a: (0, "x" * 50))
    assert len(ex.executer(Action("commande", {"texte": "x"})).corps) < 50


def test_chercher_ne_sort_pas_du_dossier(ex, tmp_path):
    secret = tmp_path.parent / f"secret-{tmp_path.name}.txt"
    secret.write_text("motdepasse", encoding="utf-8")
    try:
        r = ex.executer(Action("chercher", {"motif": "motdepasse", "glob": "../*"}))
        assert "motdepasse" not in r.corps
        assert r.ok is False and "hors du dossier" in r.corps
    finally:
        secret.unlink()
