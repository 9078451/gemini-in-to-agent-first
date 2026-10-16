from cowork.actions import Resultat
from cowork.boucle import executer
from cowork.format import Action
from cowork.surete import Verdict

ACTION_LIRE = '```json\n{"action":"lire","chemin":"a"}\n```'
ACTION_SUPPR = '```json\n{"action":"supprimer","chemin":"a"}\n```'


class FauxEnvoyeur:
    """Renvoie des réponses scriptées et garde la trace des messages reçus."""

    def __init__(self, reponses):
        self._reponses = list(reponses)
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)
        return self._reponses.pop(0) if self._reponses else "TERMINÉ"


class FauxExecuteur:
    def __init__(self):
        self.appels = 0

    def __call__(self, action):
        self.appels += 1
        return Resultat(True, "ok")


def types(evenements):
    return [e["type"] for e in evenements]


def lancer(reponses, executeur, classer, demander_accord, max_etapes=40):
    evenements = []
    envoyer = FauxEnvoyeur(reponses)
    executer(
        envoyer=envoyer,
        message_initial="tâche",
        executer=executeur,
        classer=classer,
        demander_accord=demander_accord,
        emettre=evenements.append,
        max_etapes=max_etapes,
        echecs_max=3,
        taille_max=8000,
    )
    return evenements, envoyer


TOUT_SUR = lambda action: Verdict(False)
TOUT_DANGEREUX = lambda action: Verdict(True, "danger")
JAMAIS_DEMANDE = lambda action, raison: True
ACCORD_OUI = lambda action, raison: True
ACCORD_NON = lambda action, raison: False


def test_enchaine_puis_termine():
    ex = FauxExecuteur()
    evenements, _ = lancer([ACTION_LIRE, "TERMINÉ : fait"], ex, TOUT_SUR, JAMAIS_DEMANDE)
    assert types(evenements) == ["action", "resultat", "termine"]
    assert ex.appels == 1


def test_action_dangereuse_demande_accord_accepte():
    ex = FauxExecuteur()
    evenements, _ = lancer([ACTION_SUPPR, "TERMINÉ"], ex, TOUT_DANGEREUX, ACCORD_OUI)
    assert "demande" in types(evenements) and ex.appels == 1


def test_refus_continue_la_boucle():
    ex = FauxExecuteur()
    evenements, envoyer = lancer([ACTION_SUPPR, "TERMINÉ"], ex, TOUT_DANGEREUX, ACCORD_NON)
    assert "refus" in types(evenements)
    assert ex.appels == 0
    assert "refus" in envoyer.messages[-1].lower() or "ERREUR" in envoyer.messages[-1]


def test_format_casse_rappelle_puis_arrete():
    ex = FauxExecuteur()
    evenements, _ = lancer(["n'importe quoi"] * 3, ex, TOUT_SUR, JAMAIS_DEMANDE)
    assert types(evenements).count("erreur_format") == 3


def test_limite_d_etapes():
    ex = FauxExecuteur()
    evenements, _ = lancer([ACTION_LIRE] * 10, ex, TOUT_SUR, JAMAIS_DEMANDE, max_etapes=5)
    assert types(evenements)[-1] == "limite"
    assert ex.appels == 5
