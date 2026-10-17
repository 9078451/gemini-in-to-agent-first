import pytest

from pilote.attente import attendre_envoi, attendre_fin_reponse, attendre_nouvelle_reponse, erreur_envoi
from pilote.erreurs import DelaiDepasse, LimiteGemini, MessageAbandonne, MessageNonEnvoye


class Horloge:
    """Fausse horloge : le temps n'avance que quand on « dort »."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def dormir(self, secondes: float) -> None:
        self.t += secondes


def suite_de_textes(*textes: str):
    """Renvoie les textes un par un, puis répète le dernier."""
    restants = list(textes)

    def lire() -> str:
        return restants.pop(0) if len(restants) > 1 else restants[0]

    return lire


def attendre(lire, en_cours, horloge, delai_max=180.0):
    return attendre_fin_reponse(
        lire, en_cours, delai_max=delai_max, stabilite=2.0,
        intervalle=0.5, horloge=horloge, dormir=horloge.dormir,
    )


def test_texte_stable_rendu_apres_stabilite():
    h = Horloge()
    assert attendre(lambda: "Bonjour", lambda: False, h) == "Bonjour"
    assert h.t == pytest.approx(2.0)


def test_attend_que_le_texte_arrete_de_grandir():
    h = Horloge()
    lire = suite_de_textes("", "Bon", "Bonjour", "Bonjour !")
    assert attendre(lire, lambda: False, h) == "Bonjour !"


def test_attend_la_fin_de_la_generation():
    h = Horloge()
    assert attendre(lambda: "Bonjour", lambda: h.t < 5.0, h) == "Bonjour"
    assert h.t >= 5.0


def test_texte_vide_finit_en_delai_depasse():
    h = Horloge()
    with pytest.raises(DelaiDepasse) as erreur:
        attendre(lambda: "", lambda: False, h, delai_max=10.0)
    assert erreur.value.partiel == ""


def test_generation_sans_fin_renvoie_le_debut():
    h = Horloge()
    with pytest.raises(DelaiDepasse) as erreur:
        attendre(lambda: "Début de réponse", lambda: True, h, delai_max=10.0)
    assert erreur.value.partiel == "Début de réponse"
    assert "Début de réponse" in str(erreur.value)


def test_envoi_confirme_quand_la_question_apparait():
    horloge = Horloge()
    comptes = iter([1, 1, 1, 2])
    attendre_envoi(lambda: next(comptes), nb_avant=1, delai=15.0, horloge=horloge, dormir=horloge.dormir)
    assert horloge.t < 15.0


def test_envoi_non_confirme_leve_une_erreur_claire():
    # Sans cette vérification, un message resté dans le champ faisait attendre toute la limite (10 min).
    horloge = Horloge()
    with pytest.raises(MessageNonEnvoye):
        attendre_envoi(lambda: 1, nb_avant=1, delai=15.0, horloge=horloge, dormir=horloge.dormir)
    assert 15.0 <= horloge.t < 17.0


def test_envoi_refuse_sans_bandeau():
    assert isinstance(erreur_envoi(None), MessageNonEnvoye)


def test_envoi_refuse_avec_bandeau_de_limite():
    # Compte arrivé à sa limite d'utilisation : Gemini garde le message dans le champ.
    erreur = erreur_envoi("Votre limite sera réinitialisée à 2:58 PM")
    assert isinstance(erreur, LimiteGemini)
    assert "2:58 PM" in str(erreur)



# --- Gemini abandonne un message (trouvé en essai réel : 4 Argon Max. sur une longue demande) ---

def compteur(*valeurs):
    """Renvoie les valeurs une par une, puis répète la dernière."""
    restantes = list(valeurs)
    return lambda: restantes.pop(0) if len(restantes) > 1 else restantes[0]


def attendre_reponse(reponses, questions, en_cours, horloge, delai=600.0):
    return attendre_nouvelle_reponse(
        reponses, questions, en_cours, nb_reponses_avant=0, nb_questions_attendu=1, delai=delai,
        patience_abandon=8.0, intervalle=0.5, horloge=horloge, dormir=horloge.dormir,
    )


def test_nouvelle_reponse_trouvee():
    assert attendre_reponse(compteur(0, 0, 1), compteur(1), lambda: True, Horloge()) is True


def test_question_disparue_sans_generation_leve_message_abandonne():
    horloge = Horloge()
    with pytest.raises(MessageAbandonne) as erreur:
        attendre_reponse(compteur(0), compteur(1, 1, 0), lambda: False, horloge)
    assert horloge.t < 20  # quelques secondes, pas les 10 minutes du délai
    assert "Min." in str(erreur.value)


def test_disparition_breve_toleree():
    # En passant de /app à /app/<id>, Gemini redessine la page : la question peut manquer un instant.
    questions = compteur(1, 0, 0, 0, 1)
    assert attendre_reponse(compteur(0, 0, 0, 0, 0, 0, 1), questions, lambda: False, Horloge()) is True


def test_question_absente_mais_generation_en_cours_pas_d_abandon():
    horloge = Horloge()
    with pytest.raises(DelaiDepasse):
        attendre_reponse(compteur(0), compteur(0), lambda: True, horloge, delai=60.0)


def test_delai_sans_generation_ni_abandon_renvoie_faux():
    assert attendre_reponse(compteur(0), compteur(1), lambda: False, Horloge(), delai=30.0) is False
