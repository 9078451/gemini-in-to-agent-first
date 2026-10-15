from pilote.modeles import Modes, Option
from pilote.modes import motif_libelle


def test_libelle_avec_espace_insecable():
    assert motif_libelle("3.1 Pro").fullmatch(" 3.1\xa0Pro ")


def test_libelle_exact_seulement():
    assert not motif_libelle("3.1 Pro").fullmatch(" 3.1\xa0Pro Max ")
    assert not motif_libelle("3.1 Pro").fullmatch("3.1Pro")


def test_modes_actifs():
    modes = Modes(
        [Option("3.1 Pro", "Raisonnement avancé"), Option("4 Argon", "Tâches complexes", True)],
        [Option("Min.", "Rapide et efficace", True), Option("Max.", "Très poussé")],
    )
    assert (modes.modele_actif, modes.niveau_actif) == ("4 Argon", "Min.")
    assert Modes([], []).modele_actif is None
