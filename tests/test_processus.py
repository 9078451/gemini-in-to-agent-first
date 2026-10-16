import sys
import time

import pytest

from cowork.actions import Executeur
from cowork.format import Action
from cowork.processus import GestionnaireProcessus

PRET_PUIS_DORT = "import time; print('pret', flush=True); time.sleep(30)"
DORT = "import time; time.sleep(30)"


@pytest.fixture
def changements():
    return []


@pytest.fixture
def gestion(tmp_path, changements):
    g = GestionnaireProcessus(
        tmp_path, max_processus=2, attente_demarrage=0.5, taille_max=8000,
        commande=lambda texte: [sys.executable, "-c", texte], au_changement=changements.append,
    )
    yield g
    g.arreter_tout()


def test_demarrer_puis_sortie(gestion):
    r = gestion.demarrer(PRET_PUIS_DORT)
    assert r.ok and r.corps.startswith("started #1 (pid ") and "pret" in r.corps
    assert gestion.liste()[0]["actif"] is True and gestion.liste()[0]["commande"] == PRET_PUIS_DORT


def test_processus_muet_ne_bloque_pas(gestion):
    debut = time.monotonic()
    r = gestion.demarrer(DORT)
    assert r.ok and "(no output yet)" in r.corps
    assert time.monotonic() - debut < 3


def test_mort_au_demarrage(gestion):
    r = gestion.demarrer("print('boum', flush=True); raise SystemExit(3)")
    assert r.ok is False and r.code == 3 and "boum" in r.corps
    assert gestion.liste()[0]["actif"] is False


def test_logs_seulement_le_nouveau(gestion):
    demarrage = gestion.demarrer("import time\nfor i in range(3):\n    print(f'ligne{i}', flush=True)\ntime.sleep(30)")
    assert "ligne2" in demarrage.corps  # lue au démarrage…
    assert gestion.sortie("1").corps == "(no new output)"  # … donc pas renvoyée une 2ᵉ fois
    gestion.demarrer("import time\ntime.sleep(1)\nprint('apres', flush=True)\ntime.sleep(30)")
    time.sleep(1.5)
    assert "apres" in gestion.sortie("2").corps


def test_arreter(gestion):
    gestion.demarrer(DORT)
    r = gestion.arreter("1")
    assert r.ok and "stopped #1" in r.corps
    assert gestion.liste()[0]["actif"] is False


def test_arreter_inconnu(gestion):
    r = gestion.arreter("9")
    assert r.ok is False and "no process #9" in r.corps
    assert gestion.sortie("x").ok is False


def test_limite(gestion):
    gestion.demarrer(DORT)
    gestion.demarrer(DORT)
    r = gestion.demarrer(DORT)
    assert r.ok is False and "stop one first" in r.corps


def test_un_processus_fini_libere_une_place(gestion):
    gestion.demarrer("print('fini')")
    gestion.demarrer(DORT)
    assert gestion.demarrer(DORT).ok


def test_arreter_tout(gestion):
    gestion.demarrer(DORT)
    gestion.demarrer(DORT)
    gestion.arreter_tout()
    assert not any(p["actif"] for p in gestion.liste())


def test_au_changement_appele(gestion, changements):
    gestion.demarrer(DORT)
    gestion.arreter("1")
    assert len(changements) >= 2
    assert changements[0][0]["actif"] is True and changements[-1][0]["actif"] is False


def test_executeur_branche_start_logs_stop(tmp_path, gestion):
    ex = Executeur(tmp_path, 5, 8000, processus=gestion)
    assert ex.executer(Action("start", {"command": PRET_PUIS_DORT})).ok
    assert ex.executer(Action("logs", {"id": "1"})).ok
    assert ex.executer(Action("stop", {"id": "1"})).ok
    assert gestion.liste()[0]["actif"] is False


def test_powershell_par_defaut(tmp_path):
    g = GestionnaireProcessus(tmp_path, max_processus=1, attente_demarrage=3, taille_max=8000)
    try:
        r = g.demarrer("Write-Output 'serveur prêt'; Start-Sleep 30")
        assert r.ok and "serveur prêt" in r.corps
    finally:
        g.arreter_tout()
