import os

import pytest

from cowork.catalogue import Action, Resultat
from cowork.tache import EtatTache, lire_plan


def test_lire_plan_liste():
    assert lire_plan(["[x] lire", "[ ] écrire", "- [X] tester", "sans case"]) == [
        {"texte": "lire", "fait": True},
        {"texte": "écrire", "fait": False},
        {"texte": "tester", "fait": True},
        {"texte": "sans case", "fait": False},
    ]


def test_lire_plan_texte():
    assert lire_plan("[x] a\n\n[ ] b") == [{"texte": "a", "fait": True}, {"texte": "b", "fait": False}]


def creer(tache, chemin, effet="cree"):
    tache.noter(Action("create", {"path": chemin, "content": ""}), Resultat(True, "", effet=(effet, chemin)))


def test_bilan_cree_puis_modifie_reste_cree():
    tache = EtatTache()
    creer(tache, "a.py")
    creer(tache, "a.py", "modifie")
    creer(tache, "b.py", "modifie")
    bilan = tache.bilan([])
    assert bilan["crees"] == ["a.py"] and bilan["modifies"] == ["b.py"] and bilan["supprimes"] == []


def test_bilan_cree_puis_supprime_disparait():
    tache = EtatTache()
    creer(tache, "a.py")
    tache.noter(Action("delete", {"path": "a.py"}), Resultat(True, "", effet=("supprime", "a.py")))
    tache.noter(Action("delete", {"path": "c.py"}), Resultat(True, "", effet=("supprime", "c.py")))
    bilan = tache.bilan([])
    assert bilan["crees"] == [] and bilan["supprimes"] == ["c.py"]


def test_bilan_meme_fichier_sous_plusieurs_ecritures():
    tache = EtatTache()
    creer(tache, "./src/a.py")
    creer(tache, "src/a.py", "modifie")
    creer(tache, "src//b.py", "modifie")
    creer(tache, "src/./b.py", "modifie")
    creer(tache, "c.py", "supprime")
    creer(tache, "./c.py", "supprime")
    bilan = tache.bilan([])
    assert bilan["crees"] == ["src/a.py"] and bilan["modifies"] == ["src/b.py"] and bilan["supprimes"] == ["c.py"]


@pytest.mark.skipif(os.name != "nt", reason="la casse ne compte pas sous Windows seulement")
def test_bilan_casse_ignoree_sous_windows():
    tache = EtatTache()
    creer(tache, "A.py")
    creer(tache, "a.py", "modifie")
    creer(tache, "a.PY", "supprime")
    creer(tache, "B.py", "modifie")
    creer(tache, "b.py", "modifie")
    bilan = tache.bilan([])
    assert bilan["crees"] == [] and bilan["modifies"] == ["B.py"] and bilan["supprimes"] == []


def test_bilan_commandes_plan_processus():
    tache = EtatTache(plan=lire_plan(["[x] a", "[ ] b"]))
    tache.noter(Action("run", {"command": "pytest"}), Resultat(False, "", code=1))
    processus = [{"id": 1, "actif": True}, {"id": 2, "actif": False}]
    bilan = tache.bilan(processus)
    assert bilan["commandes"] == [{"texte": "pytest", "code": 1}]
    assert bilan["verifications"] == 1 and bilan["plan_inacheve"] == ["b"]
    assert bilan["processus"] == [{"id": 1, "actif": True}]


def test_ecriture_puis_verification():
    tache = EtatTache()
    creer(tache, "a.py")
    assert tache.ecrit_depuis_verif is True
    tache.noter(Action("visit", {"url": "http://localhost/"}), Resultat(True, "HTTP 200"))
    assert tache.ecrit_depuis_verif is False


def test_texte_seul_ne_demande_pas_de_verification():
    tache = EtatTache()
    creer(tache, "notes.md")
    creer(tache, "LISEZMOI.TXT")
    assert tache.ecrit_depuis_verif is False


def test_echec_d_ecriture_ignore():
    tache = EtatTache()
    tache.noter(Action("create", {"path": "a.py", "content": ""}), Resultat(False, "boum"))
    assert tache.ecrit_depuis_verif is False and tache.bilan([])["crees"] == []


def test_aller_retour_dict():
    tache = EtatTache(plan=lire_plan(["[ ] a"]), relances=1, verif_demandee=True)
    creer(tache, "a.py")
    copie = EtatTache.depuis_dict(tache.vers_dict())
    assert copie == tache
    assert EtatTache.depuis_dict({"plan": [], "inconnu": 3}) == EtatTache()


def test_bilan_donne_les_temps():
    tache = EtatTache(temps_gemini=73.44, temps_actions=5.06)
    assert tache.bilan([])["temps"] == {"gemini": 73.4, "actions": 5.1}
