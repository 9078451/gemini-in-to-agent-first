import threading
import time

import pytest

from agent_first.file_attente import FileAttente
from pilote.erreurs import PasConnecteGoogle


class FauxPilote:
    def __init__(self) -> None:
        self.en_cours = 0
        self.max_en_meme_temps = 0
        self.verrou = threading.Lock()

    def travailler(self, duree: float) -> str:
        with self.verrou:
            self.en_cours += 1
            self.max_en_meme_temps = max(self.max_en_meme_temps, self.en_cours)
        time.sleep(duree)
        with self.verrou:
            self.en_cours -= 1
        return "fait"


@pytest.fixture
def fabrique():
    appels = []

    def fabriquer():
        appels.append(threading.current_thread().name)
        return FauxPilote()

    fabriquer.appels = appels
    return fabriquer


@pytest.fixture
def file(fabrique):
    f = FileAttente(fabrique)
    f.demarrer()
    yield f
    f.arreter()


def test_renvoie_le_resultat(file):
    assert file.soumettre(lambda p: p.travailler(0)).result(timeout=5) == "fait"


def test_un_seul_message_a_la_fois(file):
    futurs = [file.soumettre(lambda p: p.travailler(0.05)) for _ in range(4)]
    pilotes = [f.result(timeout=5) for f in futurs]
    assert pilotes == ["fait"] * 4
    assert file.soumettre(lambda p: p.max_en_meme_temps).result(timeout=5) == 1


def test_pilote_fabrique_une_fois_dans_le_fil_de_la_file(file, fabrique):
    file.soumettre(lambda p: p.travailler(0)).result(timeout=5)
    file.soumettre(lambda p: p.travailler(0)).result(timeout=5)
    assert fabrique.appels == ["file-gemini"]


def test_erreur_transmise_et_file_continue(file):
    def echoue(_pilote):
        raise PasConnecteGoogle()

    with pytest.raises(PasConnecteGoogle):
        file.soumettre(echoue).result(timeout=5)
    assert file.soumettre(lambda p: p.travailler(0)).result(timeout=5) == "fait"


def test_occupee_tant_qu_une_demande_tourne_ou_attend(file):
    assert not file.occupee()
    libere = threading.Event()
    premiere = file.soumettre(lambda p: libere.wait(5))
    seconde = file.soumettre(lambda p: p.travailler(0))
    assert file.occupee()
    libere.set()
    premiere.result(timeout=5)
    seconde.result(timeout=5)
    fin = time.monotonic() + 2
    while file.occupee() and time.monotonic() < fin:
        time.sleep(0.01)
    assert not file.occupee()
