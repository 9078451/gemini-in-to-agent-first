from pilote.modeles import Modes, Option
from pilote.erreurs import ChoixBloque
from pilote.modes import limite_de, motif_libelle


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


def test_option_bloquee_par_la_limite():
    # Quand le compte a atteint sa limite, Gemini remplace la description de l'option.
    assert limite_de("Réinitialisation de la limite : 16 oct., 14:58") == "16 oct., 14:58"
    assert limite_de("Réinitialisation de la limite : 16 oct., 14:58") == "16 oct., 14:58"


def test_option_libre():
    assert limite_de("Réponses les plus rapides") is None
    assert limite_de("") is None


def test_message_choix_bloque():
    message = str(ChoixBloque("3.8 Flash", "16 oct., 14:58"))
    assert "3.8 Flash" in message and "16 oct., 14:58" in message and "limite" in message
