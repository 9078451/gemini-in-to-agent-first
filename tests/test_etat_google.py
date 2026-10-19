from concurrent.futures import Future

from agent_first.etat_google import EtatGoogle


class FauxPilote:
    def __init__(self, connecte=True):
        self.connecte = connecte

    def est_connecte(self):
        return self.connecte


class FauxFile:
    def __init__(self, pilote, occupee=False):
        self.pilote = pilote
        self.occupe = occupee
        self.soumis = 0

    def occupee(self):
        return self.occupe

    def soumettre(self, travail):
        self.soumis += 1
        futur = Future()
        futur.set_result(travail(self.pilote))
        return futur


class Horloge:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_chrome_ferme_inconnu_sans_rien_demander():
    file = FauxFile(FauxPilote())
    assert EtatGoogle(file, lambda: False).lire() is None
    assert file.soumis == 0


def test_lu_une_fois_puis_garde():
    file, horloge = FauxFile(FauxPilote()), Horloge()
    etat = EtatGoogle(file, lambda: True, age_max=60, horloge=horloge)
    assert etat.lire() is True
    horloge.t += 30
    assert etat.lire() is True
    assert file.soumis == 1
    horloge.t += 31
    etat.lire()
    assert file.soumis == 2


def test_file_occupee_ne_fait_pas_la_queue():
    file, horloge = FauxFile(FauxPilote()), Horloge()
    etat = EtatGoogle(file, lambda: True, age_max=60, horloge=horloge)
    etat.lire()
    horloge.t += 120
    file.occupe = True
    assert etat.lire() is True  # l'ancien état, tout de suite
    assert file.soumis == 1


def test_etat_note_par_un_envoi():
    file = FauxFile(FauxPilote())
    etat = EtatGoogle(file, lambda: True)
    etat.noter(False)
    assert etat.lire() is False
    assert file.soumis == 0
