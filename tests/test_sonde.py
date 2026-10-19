from pilote.sonde import SONDER, Sonde


class FaussePage:
    def __init__(self, *etats):
        self.etats = list(etats)
        self.appels = []

    def evaluate(self, script, arguments):
        self.appels.append((script, arguments))
        return self.etats.pop(0) if len(self.etats) > 1 else self.etats[0]


class Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


REPERES = {"question": ["user-query"], "reponse": ["model-response"], "generation": ["button.stop"], "limite": []}


def test_un_seul_aller_retour_par_tour_de_boucle():
    page, horloge = FaussePage({"questions": 2, "reponses": 1, "generation": True, "texte": "Bon"}), Horloge()
    sonde = Sonde(page, REPERES, horloge=horloge)
    assert (sonde.questions(), sonde.reponses(), sonde.generation(), sonde.texte()) == (2, 1, True, "Bon")
    assert len(page.appels) == 1
    assert page.appels[0][0] == SONDER


def test_relue_apres_la_fraicheur():
    page, horloge = FaussePage({"texte": "Bon"}, {"texte": "Bonjour"}), Horloge()
    sonde = Sonde(page, REPERES, fraicheur=0.05, horloge=horloge)
    assert sonde.texte() == "Bon"
    horloge.t = 0.06
    assert sonde.texte() == "Bonjour"


def test_valeurs_manquantes_completees():
    sonde = Sonde(FaussePage({}), REPERES)
    assert (sonde.questions(), sonde.generation(), sonde.limite(), sonde.html()) == (0, False, None, "")


def test_viser_une_reponse_relit_tout_de_suite():
    page, horloge = FaussePage({"texte": "ancienne"}, {"texte": "nouvelle"}), Horloge()
    sonde = Sonde(page, REPERES, horloge=horloge)
    sonde.texte()
    sonde.viser(3)
    assert sonde.texte() == "nouvelle"
    assert page.appels[-1][1]["indice"] == 3
