from pilote.gemini import reglages_a_faire


def test_premier_message_regle_tout():
    assert reglages_a_faire(None, None, "3.1 Pro", "Max.") == (True, True)


def test_rien_a_changer():
    assert reglages_a_faire("3.1 Pro", "Max.", "3.1 Pro", "Max.") == (False, False)


def test_niveau_seul():
    assert reglages_a_faire("3.1 Pro", "Min.", "3.1 Pro", "Max.") == (False, True)


def test_changer_de_modele_reapplique_le_niveau():
    assert reglages_a_faire("4 Argon", "Max.", "3.1 Pro", "Max.") == (True, True)


def test_rien_demande():
    assert reglages_a_faire("4 Argon", "Min.", None, None) == (False, False)
