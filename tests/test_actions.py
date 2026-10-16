import subprocess

import pytest

from cowork.actions import Executeur, lancer_powershell
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


def creer(chemin, contenu):
    return Action("create", {"path": chemin, "content": contenu})


def test_creer_puis_lire(ex, tmp_path):
    assert ex.executer(creer("a.txt", "bonjour")).ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "bonjour"
    assert ex.executer(Action("read", {"path": "a.txt"})).corps == "bonjour"


def test_creer_nouveau(ex):
    r = ex.executer(creer("a.txt", "un\ndeux\n"))
    assert r.effet == ("cree", "a.txt") and r.corps == "a.txt created (2 lines)"


def test_creer_fabrique_les_dossiers(ex, tmp_path):
    assert ex.executer(creer("a/b/c.txt", "x")).ok
    assert (tmp_path / "a" / "b" / "c.txt").exists()


def test_reecrire_donne_un_diff(ex, tmp_path):
    (tmp_path / "a.txt").write_text("ancien\n", encoding="utf-8")
    r = ex.executer(creer("a.txt", "nouveau\n"))
    assert r.effet == ("modifie", "a.txt")
    assert "-ancien" in r.diff and "+nouveau" in r.diff


def test_lister(ex, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "d").mkdir()
    assert ex.executer(Action("list", {})).corps == "a.txt\nd/"


def test_lister_un_fichier(ex, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert ex.executer(Action("list", {"path": "a.txt"})).ok is False


def test_edit_unique(ex, tmp_path):
    (tmp_path / "a.txt").write_text("un\nrouge\ntrois\n", encoding="utf-8")
    r = ex.executer(Action("edit", {"path": "a.txt", "old": "rouge", "new": "vert"}))
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "un\nvert\ntrois\n"
    assert "-rouge" in r.diff and "+vert" in r.diff and r.effet == ("modifie", "a.txt")


def test_edit_introuvable_montre_le_passage_proche(ex, tmp_path):
    (tmp_path / "a.py").write_text("import os\n\ndef f():\n    return 1\n", encoding="utf-8")
    r = ex.executer(Action("edit", {"path": "a.py", "old": "def f():\n  return 1", "new": "x"}))
    assert r.ok is False
    assert "Closest passage (lines 3-4)" in r.corps and "    return 1" in r.corps


def test_edit_introuvable_sans_passage_proche(ex, tmp_path):
    (tmp_path / "a.txt").write_text("abc\n", encoding="utf-8")
    r = ex.executer(Action("edit", {"path": "a.txt", "old": "zzzzzzzzzzzz", "new": "x"}))
    assert r.ok is False and "No similar passage" in r.corps


def test_edit_plusieurs_fois(ex, tmp_path):
    (tmp_path / "a.txt").write_text("x = 1\nx = 1\n", encoding="utf-8")
    r = ex.executer(Action("edit", {"path": "a.txt", "old": "x = 1", "new": "x = 2"}))
    assert r.ok is False and "appears 2 times" in r.corps
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x = 1\nx = 1\n"


def test_chercher(ex, tmp_path):
    (tmp_path / "a.txt").write_text("alpha\nbeta", encoding="utf-8")
    assert "a.txt:2: beta" in ex.executer(Action("search", {"pattern": "beta"})).corps


def test_supprimer(ex, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    r = ex.executer(Action("delete", {"path": "a.txt"}))
    assert r.ok and r.effet == ("supprime", "a.txt")
    assert not (tmp_path / "a.txt").exists()


def test_resoudre_refuse_hors_dossier(ex):
    for chemin in ("../secret.txt", "C:/Windows/x.txt"):
        r = ex.executer(Action("read", {"path": chemin}))
        assert r.ok is False and "outside the working folder" in r.corps


def test_chemins_windows(ex, tmp_path):
    assert ex.executer(creer("app\\views\\x.html", "<p>")).ok
    assert ex.executer(Action("read", {"path": "app/views/x.html"})).corps == "<p>"
    for chemin in ("C:\\Windows\\win.ini", "..\\x"):
        r = ex.executer(Action("read", {"path": chemin}))
        assert r.ok is False and "outside the working folder" in r.corps


def test_fichier_absent_renvoie_une_erreur(ex):
    r = ex.executer(Action("read", {"path": "x.txt"}))
    assert r.ok is False and "not found" in r.corps


def test_champ_manquant_renvoie_une_erreur(ex):
    r = ex.executer(Action("create", {"path": "a"}))
    assert r.ok is False and r.corps == 'missing field "content"'


def test_action_inconnue(ex):
    r = ex.executer(Action("fly", {}))
    assert r.ok is False and r.corps.startswith("unknown action")


def test_aucune_exception_ne_sort(ex, tmp_path):
    (tmp_path / "d").mkdir()
    assert ex.executer(Action("read", {"path": "d"})).ok is False
    assert ex.executer(Action("edit", {"path": "absent.txt", "old": "a", "new": "b"})).ok is False
    assert ex.executer(Action("delete", {"path": "absent.txt"})).ok is False


def test_processus_sans_gestionnaire(ex):
    assert ex.executer(Action("start", {"command": "python s.py"})).ok is False


def test_commande_passe_par_lancer(ex, appels, tmp_path):
    r = ex.executer(Action("run", {"command": "echo bonjour"}))
    assert r.ok and r.corps == "sortie simulée" and r.code == 0
    assert appels == [("echo bonjour", tmp_path, 5)]


def test_commande_code_de_sortie(tmp_path):
    ex = Executeur(tmp_path, 5, 8000, lancer=lambda *a: (1, "boum"))
    r = ex.executer(Action("run", {"command": "python x.py"}))
    assert r.ok is False and r.code == 1 and r.corps == "boum"


def test_commande_trop_longue_conseille_start(tmp_path):
    def lent(*_):
        raise subprocess.TimeoutExpired("ps", 1)

    ex = Executeur(tmp_path, 1, 8000, lancer=lent)
    r = ex.executer(Action("run", {"command": "python server.py"}))
    assert r.ok is False and "use start" in r.corps


def test_sortie_coupee(tmp_path):
    ex = Executeur(tmp_path, 5, 10, lancer=lambda *a: (0, "x" * 50))
    assert len(ex.executer(Action("run", {"command": "x"})).corps) < 50


def test_chercher_ne_sort_pas_du_dossier(ex, tmp_path):
    secret = tmp_path.parent / f"secret-{tmp_path.name}.txt"
    secret.write_text("motdepasse", encoding="utf-8")
    try:
        r = ex.executer(Action("search", {"pattern": "motdepasse", "glob": "../*"}))
        assert "motdepasse" not in r.corps
        assert r.ok is False and "outside the working folder" in r.corps
    finally:
        secret.unlink()


def test_powershell_rend_les_accents(tmp_path):
    # PowerShell 5.1 écrit dans la page de code de la console (cp850) si on ne lui dit rien.
    code, sortie = lancer_powershell("Write-Output 'Répertoire : é à ç'", tmp_path, 60)
    assert code == 0
    assert "Répertoire : é à ç" in sortie


def test_python_lance_par_powershell_rend_les_accents(tmp_path):
    (tmp_path / "a.py").write_text("print('été')", encoding="utf-8")
    code, sortie = lancer_powershell("python a.py", tmp_path, 60)
    assert code == 0
    assert "été" in sortie


def test_powershell_trop_long_tue_l_arbre(tmp_path):
    # Un python lancé par PowerShell survivait au délai ; il doit être tué avec PowerShell.
    marque = tmp_path / "vivant.txt"
    script = tmp_path / "boucle.py"
    script.write_text(
        "import time, pathlib\nfor i in range(100):\n    pathlib.Path('vivant.txt').write_text(str(i))\n    time.sleep(0.2)\n",
        encoding="utf-8",
    )
    with pytest.raises(subprocess.TimeoutExpired):
        lancer_powershell("python boucle.py", tmp_path, 3)
    import time

    time.sleep(1)
    avant = marque.read_text()
    time.sleep(1)
    assert marque.read_text() == avant


def test_edit_garde_les_fins_de_ligne_lf(ex, tmp_path):
    (tmp_path / "a.py").write_bytes(b"un\ndeux\n")
    assert ex.executer(Action("edit", {"path": "a.py", "old": "deux", "new": "trois"})).ok
    assert (tmp_path / "a.py").read_bytes() == b"un\ntrois\n"


def test_edit_garde_les_fins_de_ligne_crlf(ex, tmp_path):
    (tmp_path / "a.py").write_bytes(b"un\r\ndeux\r\n")
    assert ex.executer(Action("edit", {"path": "a.py", "old": "un\ndeux", "new": "un\ntrois"})).ok
    assert (tmp_path / "a.py").read_bytes() == b"un\r\ntrois\r\n"


def test_powershell_arrete_par_l_utilisateur(tmp_path):
    import threading
    import time

    script = tmp_path / "long.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    arret = threading.Event()
    threading.Timer(1.0, arret.set).start()
    debut = time.monotonic()
    code, sortie = lancer_powershell("python long.py", tmp_path, 60, arret=arret)
    assert time.monotonic() - debut < 10 and code != 0 and "stopped by the user" in sortie


def test_executeur_transmet_l_arret(tmp_path):
    import threading

    recus = []
    arret = threading.Event()
    ex = Executeur(tmp_path, 5, 8000, lancer=lambda texte, dossier, delai, arret=None: recus.append(arret) or (0, "x"), arret=arret)
    ex.executer(Action("run", {"command": "dir"}))
    assert recus == [arret]


def test_passage_proche_rapide_sur_un_gros_fichier(ex, tmp_path):
    import time

    lignes = [f"    valeur_{i} = calcul({i}, 'texte {i}')" for i in range(5000)]
    (tmp_path / "gros.py").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    cherche = "\n".join(l.replace("    ", "  ") for l in lignes[2000:2040])  # mauvaise indentation
    debut = time.monotonic()
    r = ex.executer(Action("edit", {"path": "gros.py", "old": cherche, "new": "x"}))
    assert time.monotonic() - debut < 2
    assert r.ok is False and "Closest passage (lines 2001-2040)" in r.corps


def test_passage_proche_avec_une_faute(ex, tmp_path):
    (tmp_path / "a.py").write_text("def calculer_total(prix, quantite):\n    return prix * quantite\n", encoding="utf-8")
    r = ex.executer(Action("edit", {"path": "a.py", "old": "def calculer_totale(prix, quantité):", "new": "x"}))
    assert "Closest passage (lines 1-1)" in r.corps
