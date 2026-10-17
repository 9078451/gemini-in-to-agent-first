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
# Le modèle et le niveau choisis dans un onglet deviennent ceux de toute nouvelle
# discussion, dans l'autre onglet aussi (vu en essai réel, 17/10).

from pilote import gemini  # noqa: E402
from pilote.gemini import PiloteGemini, ReglagesCompte  # noqa: E402
from pilote.modeles import Modes, Option  # noqa: E402


class SelecteurDuCompte:
    """Faux sélecteur de Gemini : un seul réglage pour tout le compte, lu et changé par les pilotes."""

    def __init__(self, monkeypatch):
        self.modele, self.niveau = "4 Argon", "Min."
        self.lectures = 0
        self.choix = []
        monkeypatch.setattr(gemini.modes, "lire_modes", self.lire)
        monkeypatch.setattr(gemini.modes, "choisir_modele", self.choisir_modele)
        monkeypatch.setattr(gemini.modes, "choisir_niveau", self.choisir_niveau)

    def lire(self, _page):
        self.lectures += 1
        return Modes([Option(self.modele, "", True)], [Option(self.niveau, "", True)])

    def choisir_modele(self, _page, nom):
        self.choix.append(nom)
        self.modele = nom

    def choisir_niveau(self, _page, nom):
        self.choix.append(nom)
        self.niveau = nom
        return True


def pilote(reglages):
    return PiloteGemini(None, "https://gemini.google.com/app", 60, 2, None, reglages=reglages)


def test_le_choix_de_l_autre_onglet_est_relu_avant_d_envoyer(monkeypatch):
    selecteur = SelecteurDuCompte(monkeypatch)
    compte = ReglagesCompte()
    cowork, chat = pilote(compte), pilote(compte)
    cowork._ajuster(None, False, "4 Argon", "Min.")
    chat._ajuster(None, False, "3.8 Flash", "Min.")  # le Chat change le modèle du compte
    selecteur.choix.clear()
    cowork._ajuster(None, False, "4 Argon", "Min.")
    assert selecteur.choix == ["4 Argon", "Min."]  # sinon la tâche Cowork partirait sur 3.8 Flash


def test_rien_relu_si_personne_n_a_rien_change(monkeypatch):
    selecteur = SelecteurDuCompte(monkeypatch)
    compte = ReglagesCompte()
    cowork, chat = pilote(compte), pilote(compte)
    cowork._ajuster(None, False, "4 Argon", "Min.")
    chat._ajuster(None, False, "4 Argon", "Min.")
    lectures = selecteur.lectures
    selecteur.choix.clear()
    cowork._ajuster(None, False, "4 Argon", "Min.")
    chat._ajuster(None, False, "4 Argon", "Min.")
    assert selecteur.lectures == lectures and selecteur.choix == []


def test_conversation_rouverte_relue(monkeypatch):
    selecteur = SelecteurDuCompte(monkeypatch)
    seul = pilote(ReglagesCompte())
    seul._ajuster(None, False, "4 Argon", "Min.")
    selecteur.niveau = "Max."  # la conversation rouverte a SES réglages
    selecteur.choix.clear()
    seul._ajuster(None, True, "4 Argon", "Min.")
    assert selecteur.choix == ["Min."]


def test_rien_demande_rien_relu(monkeypatch):
    selecteur = SelecteurDuCompte(monkeypatch)
    pilote(ReglagesCompte())._ajuster(None, True, None, None)
    assert selecteur.lectures == 0 and selecteur.choix == []
