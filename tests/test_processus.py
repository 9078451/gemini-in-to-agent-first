import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cowork.actions import Executeur, tuer_arbre
from cowork.format import Action
from cowork.processus import GestionnaireProcessus

PRET_PUIS_DORT = "import time; print('pret', flush=True); time.sleep(30)"
DORT = "import time; time.sleep(30)"
RACINE = Path(__file__).resolve().parent.parent
# Un Agent First qui lance un serveur (lui-même parent d'un autre processus) puis plante.
AGENT_PLANTE = """
import os, sys
from pathlib import Path
from cowork.processus import GestionnaireProcessus
g = GestionnaireProcessus(Path(sys.argv[1]), 1, 2.0, 8000, commande=lambda texte: [sys.executable, "-c", texte])
print(g.demarrer(sys.argv[2]).corps, flush=True)
os._exit(1)  # planté : ni arreter_tout, ni finally
"""
AVEC_ENFANT = (
    "import subprocess, sys, time; "
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "print('enfant', p.pid, flush=True); time.sleep(60)"
)


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


def test_sortie_d_un_print_sans_flush(tmp_path):
    # Python garde ses print() en mémoire quand sa sortie est un tube : un serveur semblait muet.
    g = GestionnaireProcessus(tmp_path, 1, 1.0, 8000, commande=lambda texte: [sys.executable, "-c", texte])
    try:
        r = g.demarrer("print('Serving on 8000')\nimport time\ntime.sleep(30)")
        assert "Serving on 8000" in r.corps
    finally:
        g.arreter_tout()


def _vivant(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32")
    k.OpenProcess.argtypes, k.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
    k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    poignee = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not poignee:
        return False
    try:
        return k.WaitForSingleObject(poignee, 0) == 0x102  # WAIT_TIMEOUT : il tourne encore
    finally:
        k.CloseHandle(poignee)


@pytest.mark.skipif(os.name != "nt", reason="Job Object : Windows seulement")
def test_processus_meurent_avec_agent_first_meme_plante(tmp_path):
    sortie = subprocess.run(
        [sys.executable, "-c", AGENT_PLANTE, str(tmp_path), AVEC_ENFANT],
        cwd=RACINE, capture_output=True, text=True, timeout=30,
    ).stdout
    pids = [int(n) for n in re.findall(r"(?:pid |enfant )(\d+)", sortie)]
    assert len(pids) == 2, sortie
    try:
        fin = time.monotonic() + 5
        while any(_vivant(pid) for pid in pids) and time.monotonic() < fin:
            time.sleep(0.1)
        assert not [pid for pid in pids if _vivant(pid)]
    finally:
        for pid in pids:
            tuer_arbre(pid)
