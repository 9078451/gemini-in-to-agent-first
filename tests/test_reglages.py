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


from pilote.gemini import nouvelle_discussion_prete

NOUVELLE = "https://gemini.google.com/app"


def test_accueil_deja_pret_pas_de_rechargement():
    assert nouvelle_discussion_prete(NOUVELLE, NOUVELLE, 0) is True
    assert nouvelle_discussion_prete(NOUVELLE + "/", NOUVELLE, 0) is True


def test_conversation_ouverte_ou_question_affichee_recharge():
    assert nouvelle_discussion_prete(NOUVELLE + "/abc123", NOUVELLE, 0) is False
    assert nouvelle_discussion_prete(NOUVELLE, NOUVELLE, 1) is False
    assert nouvelle_discussion_prete("about:blank", NOUVELLE, 0) is False


# ---- deux onglets, un seul compte ------------------------------------------
# Vu en essai réel (17/10) : une nouvelle discussion reprend le dernier modèle et
# le dernier niveau choisis, dans n'importe quel onglet ; une page déjà ouverte
# garde les siens, même quand l'autre onglet en change.

import pytest  # noqa: E402

from pilote import gemini  # noqa: E402
from pilote.gemini import PiloteGemini, ReglagesCompte  # noqa: E402
from pilote.modeles import Modes, Option  # noqa: E402


class FauxGemini:
    """Les réglages du compte (repris par une discussion neuve) et ceux de chaque page."""

    def __init__(self, monkeypatch, modele="4 Argon", niveau="Min."):
        self.compte = (modele, niveau)
        self.lectures = 0
        self.choix = []
        self.pendant_un_choix = None  # appelé au milieu d'un choix (l'autre onglet agit à ce moment-là)
        monkeypatch.setattr(gemini.modes, "lire_modes", self.lire)
        monkeypatch.setattr(gemini.modes, "choisir_modele", self.choisir_modele)
        monkeypatch.setattr(gemini.modes, "choisir_niveau", self.choisir_niveau)

    def page(self):
        return FaussePage(self)

    def lire(self, page):
        self.lectures += 1
        return Modes([Option(page.reglages[0], "", True)], [Option(page.reglages[1], "", True)])

    def choisir_modele(self, page, nom):
        self.choix.append(nom)
        page.reglages = self.compte = (nom, page.reglages[1])
        if self.pendant_un_choix:
            self.pendant_un_choix()

    def choisir_niveau(self, page, nom):
        self.choix.append(nom)
        page.reglages = self.compte = (page.reglages[0], nom)
        return True


class FaussePage:
    def __init__(self, gemini_):
        self._gemini = gemini_
        self.reglages = gemini_.compte  # chargée maintenant : ceux du compte

    def goto(self, _adresse, wait_until=None):
        self.reglages = self._gemini.compte  # discussion neuve : ceux du compte


def pilote(compte):
    return PiloteGemini(None, "https://gemini.google.com/app", 60, 2, None, reglages=compte)


def test_la_page_ouverte_garde_ses_reglages_une_discussion_neuve_prend_ceux_du_compte(monkeypatch):
    # Le cas vu en essai : le Chat demande 3.8 Flash, Cowork vient de choisir 4 Argon ;
    # sans correction, la réponse du Chat partait en 4 Argon (113 s pour « 2 + 2 »).
    faux = FauxGemini(monkeypatch, "3.8 Flash", "Min.")
    compte = ReglagesCompte()
    chat, cowork = pilote(compte), pilote(compte)
    page_chat, page_cowork = faux.page(), faux.page()
    cowork._ajuster(page_cowork, "4 Argon", "Min.")  # la tâche Cowork démarre
    chat._ajuster(page_chat, "3.8 Flash", "Min.")  # page du Chat ouverte avant : toujours 3.8 Flash
    assert page_chat.reglages == ("3.8 Flash", "Min.")
    chat._discussion_neuve(page_chat)  # nouvelle conversation du Chat : elle reprend 4 Argon
    chat._ajuster(page_chat, "3.8 Flash", "Min.")
    assert page_chat.reglages == ("3.8 Flash", "Min.")


def test_cowork_retrouve_son_modele_apres_le_chat(monkeypatch):
    faux = FauxGemini(monkeypatch)
    compte = ReglagesCompte()
    cowork, chat = pilote(compte), pilote(compte)
    page_cowork, page_chat = faux.page(), faux.page()
    cowork._ajuster(page_cowork, "4 Argon", "Min.")
    chat._ajuster(page_chat, "3.8 Flash", "Min.")
    cowork._discussion_neuve(page_cowork)
    cowork._ajuster(page_cowork, "4 Argon", "Min.")
    assert page_cowork.reglages == ("4 Argon", "Min.")


def test_sans_changement_le_menu_n_est_pas_relu_a_chaque_discussion(monkeypatch):
    faux = FauxGemini(monkeypatch)
    cowork = pilote(ReglagesCompte())
    page = faux.page()
    for _ in range(3):
        cowork._discussion_neuve(page)
        cowork._ajuster(page, "4 Argon", "Min.")
    assert faux.lectures == 1 and faux.choix == []


def test_conversation_rouverte_relue(monkeypatch):
    faux = FauxGemini(monkeypatch)
    seul = pilote(ReglagesCompte())
    page = faux.page()
    seul._ajuster(page, "4 Argon", "Min.")
    page.reglages = ("4 Argon", "Max.")  # la conversation rouverte a SES réglages
    seul._conversation_rouverte()
    faux.choix.clear()
    seul._ajuster(page, "4 Argon", "Min.")
    assert faux.choix == ["Min."] and page.reglages == ("4 Argon", "Min.")


def test_onglet_rouvert_reglages_relus(monkeypatch):
    # L'utilisateur a fermé la fenêtre : l'onglet rouvert est une page inconnue.
    faux = FauxGemini(monkeypatch)
    seul = pilote(ReglagesCompte())

    class Onglet:
        def __init__(self):
            self.courante = faux.page()

        def page(self):
            return self.courante

    seul._onglet = Onglet()
    seul._ajuster(seul._page(), "4 Argon", "Min.")
    faux.compte = ("3.1 Pro", "Max.")  # changé ailleurs (à la main) : la nouvelle page le reprend
    seul._onglet.courante = faux.page()
    seul._ajuster(seul._page(), "4 Argon", "Min.")
    assert seul._onglet.courante.reglages == ("4 Argon", "Min.")


def test_rien_demande_rien_relu(monkeypatch):
    faux = FauxGemini(monkeypatch)
    pilote(ReglagesCompte())._ajuster(faux.page(), None, None)
    assert faux.lectures == 0 and faux.choix == []


def test_discussion_neuve_ouverte_pendant_un_choix_de_l_autre_onglet(monkeypatch):
    faux = FauxGemini(monkeypatch)
    compte = ReglagesCompte()
    cowork, chat = pilote(compte), pilote(compte)
    page_cowork, page_chat = faux.page(), faux.page()
    chat._discussion_neuve(page_chat)
    chat._ajuster(page_chat, "4 Argon", "Min.")  # réglages du compte connus : 4 Argon
    faux.pendant_un_choix = lambda: chat._discussion_neuve(page_chat)
    cowork._ajuster(page_cowork, "3.8 Flash", "Min.")
    faux.pendant_un_choix = None
    chat._ajuster(page_chat, "4 Argon", "Min.")
    assert page_chat.reglages == ("4 Argon", "Min.")


def test_choix_rate_a_mi_chemin_les_deux_onglets_relisent(monkeypatch):
    from pilote.erreurs import ModeleIntrouvable

    faux = FauxGemini(monkeypatch)
    compte = ReglagesCompte()
    cowork, chat = pilote(compte), pilote(compte)
    page_cowork, page_chat = faux.page(), faux.page()
    chat._discussion_neuve(page_chat)
    chat._ajuster(page_chat, "4 Argon", "Min.")
    cowork._ajuster(page_cowork, "4 Argon", "Min.")

    def rate(page, nom):  # le clic a porté, la vérification échoue
        page.reglages = faux.compte = (nom, page.reglages[1])
        raise ModeleIntrouvable(nom)

    monkeypatch.setattr(gemini.modes, "choisir_modele", rate)
    with pytest.raises(ModeleIntrouvable):
        cowork._ajuster(page_cowork, "3.8 Flash", "Min.")
    monkeypatch.setattr(gemini.modes, "choisir_modele", faux.choisir_modele)
    cowork._ajuster(page_cowork, "4 Argon", "Min.")
    chat._discussion_neuve(page_chat)
    chat._ajuster(page_chat, "4 Argon", "Min.")
    assert page_cowork.reglages == ("4 Argon", "Min.") and page_chat.reglages == ("4 Argon", "Min.")
