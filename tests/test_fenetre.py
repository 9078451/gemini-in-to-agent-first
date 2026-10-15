from gui.app import taille_fenetre, titre_conversation


def test_grand_ecran_garde_la_taille_prevue():
    assert taille_fenetre(2560, 1440, 1.0) == (1100, 720)


def test_ecran_1080p_a_150_pourcent_tient_dans_l_ecran():
    largeur, hauteur = taille_fenetre(1920, 1080, 1.5)
    assert largeur * 1.5 <= 1920
    assert hauteur * 1.5 <= 1080 * 0.85


def test_titre_sur_une_seule_ligne():
    assert titre_conversation("Ligne 1\nLigne 2") == "Ligne 1 Ligne 2"


def test_titre_long_coupe():
    titre = titre_conversation("a" * 40)
    assert len(titre) == 28
    assert titre.endswith("…")
