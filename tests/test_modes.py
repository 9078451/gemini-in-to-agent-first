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


# ---- ouvrir le sélecteur ----------------------------------------------------
# Juste après le chargement d'une nouvelle discussion, Gemini ignore le premier
# clic sur le sélecteur (vu en essai réel) : le menu reste fermé.

import pytest  # noqa: E402
from playwright.sync_api import TimeoutError as DelaiPlaywright  # noqa: E402

from pilote.erreurs import ErreurPilote  # noqa: E402
from pilote.modes import _ouvrir  # noqa: E402
from pilote.selecteurs import OPTION_MODELE  # noqa: E402


class PageMenuLent:
    """Le menu ne s'ouvre qu'au clic n° `clics_ignores + 1`."""

    def __init__(self, clics_ignores):
        self.clics = 0
        self.clics_ignores = clics_ignores

    def locator(self, selecteur):
        return ElementMenu(self, selecteur)


class ElementMenu:
    def __init__(self, page, selecteur):
        self._page, self._selecteur = page, selecteur

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def click(self):
        self._page.clics += 1

    def wait_for(self, state, timeout):
        assert self._selecteur == OPTION_MODELE and state == "visible"
        if self._page.clics <= self._page.clics_ignores:
            raise DelaiPlaywright("menu fermé")


def test_menu_reclique_si_le_premier_clic_est_ignore():
    page = PageMenuLent(clics_ignores=1)
    _ouvrir(page)
    assert page.clics == 2


def test_menu_qui_ne_s_ouvre_jamais_erreur_claire():
    with pytest.raises(ErreurPilote, match="menu des modèles"):
        _ouvrir(PageMenuLent(clics_ignores=float("inf")), delai=0.05)
