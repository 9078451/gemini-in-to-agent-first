import json

from cowork.actions import Resultat
from cowork.boucle import Branchements, Reglages, executer_tache
from cowork.surete import Verdict
from cowork.tache import EtatTache


def bloc(*actions):
    return "```json\n" + json.dumps(list(actions) if len(actions) > 1 else actions[0], ensure_ascii=False) + "\n```"


LIRE = {"action": "read", "path": "a"}
SUPPR = {"action": "delete", "path": "a"}


def creer(chemin):
    return {"action": "create", "path": chemin, "content": "x"}


def plan(*etapes):
    return {"action": "plan", "steps": list(etapes)}


def fini(resume="fait"):
    return {"action": "done", "summary": resume}


class FauxEnvoyeur:
    """Renvoie des réponses scriptées et garde la trace des messages reçus."""

    def __init__(self, reponses):
        self._reponses = list(reponses)
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)
        return self._reponses.pop(0) if self._reponses else bloc(fini())


class FauxExecuteur:
    """Réussit tout, sauf les chemins listés dans `echecs` ; note les actions reçues."""

    def __init__(self, echecs=()):
        self.actions = []
        self._echecs = set(echecs)

    def __call__(self, action):
        self.actions.append(action)
        chemin = action.champs.get("path", "")
        if chemin in self._echecs:
            return Resultat(False, "boum")
        effet = ("cree", chemin) if action.nom == "create" else None
        return Resultat(True, "ok", effet=effet)


TOUT_SUR = lambda action: Verdict(False)
TOUT_DANGEREUX = lambda action: Verdict(True, "danger")
ACCORD_OUI = lambda action, raison: True
ACCORD_NON = lambda action, raison: False


def lancer(reponses, executeur=None, classer=TOUT_SUR, accord=ACCORD_OUI, tache=None, **reglages):
    evenements = []
    envoyer = FauxEnvoyeur(reponses)
    executeur = executeur or FauxExecuteur()
    r = dict(max_tours=40, max_actions=10, echecs_max=3, taille_max=8000, taille_max_message=30000, relances_fin_max=2)
    r.update(reglages)
    executer_tache(
        "tâche", tache or EtatTache(),
        Branchements(envoyer, executeur, classer, accord, evenements.append), Reglages(**r),
    )
    return evenements, envoyer, executeur


def types(evenements):
    return [e["type"] for e in evenements]


def test_enchaine_puis_termine():
    evs, _, ex = lancer([bloc(LIRE), bloc(fini())])
    assert types(evs) == ["action", "resultat", "termine"]
    assert len(ex.actions) == 1 and evs[-1]["resume"] == "fait"


def test_lot_execute_dans_l_ordre():
    evs, envoyer, ex = lancer([bloc(creer("a.md"), creer("b.md"), creer("c.md")), bloc(fini())])
    assert [a.champs["path"] for a in ex.actions] == ["a.md", "b.md", "c.md"]
    resultats = envoyer.messages[1]
    assert resultats.startswith("RESULTS\n") and all(f"[{i}]" in resultats for i in (1, 2, 3))


def test_lot_s_arrete_a_la_premiere_erreur():
    evs, envoyer, ex = lancer([bloc(creer("a"), creer("b"), creer("c")), bloc(fini())], FauxExecuteur(echecs={"b"}))
    assert [a.champs["path"] for a in ex.actions] == ["a", "b"]
    assert "[2] create b: ERROR" in envoyer.messages[1] and "[3] create c: SKIPPED" in envoyer.messages[1]
    assert "saute" in types(evs)


def test_code_de_sortie_dans_le_resultat():
    class Commande(FauxExecuteur):
        def __call__(self, action):
            return Resultat(False, "Traceback", code=1)

    _, envoyer, _ = lancer([bloc({"action": "run", "command": "python a.py"}), bloc(fini())], Commande())
    assert '[1] run "python a.py": ERROR (exit code 1)\nTraceback' in envoyer.messages[1]


def test_action_invalide_est_une_erreur():
    evs, envoyer, ex = lancer([bloc({"action": "read"}, LIRE), bloc(fini())])
    assert ex.actions == []
    assert 'missing field "path"' in envoyer.messages[1] and "[2] read a: SKIPPED" in envoyer.messages[1]


def test_action_dangereuse_demande_accord_accepte():
    evs, _, ex = lancer([bloc(SUPPR), bloc(fini())], classer=TOUT_DANGEREUX, accord=ACCORD_OUI)
    assert "demande" in types(evs) and len(ex.actions) == 1


def test_accord_refuse_au_milieu_du_lot():
    evs, envoyer, ex = lancer([bloc(creer("a"), SUPPR, creer("c")), bloc(fini())],
                              classer=lambda a: Verdict(a.nom == "delete", "danger"), accord=ACCORD_NON)
    assert [a.nom for a in ex.actions] == ["create"]
    assert "refused by the user" in envoyer.messages[1] and "[3] create c: SKIPPED" in envoyer.messages[1]
    assert "refus" in types(evs)


def test_trop_d_actions():
    _, envoyer, ex = lancer([bloc(*[creer(f"{i}.md") for i in range(12)]), bloc(fini())])
    assert len(ex.actions) == 10 and "Only the first 10 actions were run" in envoyer.messages[1]


def test_plan_emis():
    evs, envoyer, _ = lancer([bloc(plan("[ ] a", "[ ] b")), bloc(plan("[x] a", "[x] b"), fini())])
    assert evs[0] == {"type": "plan", "etapes": [{"texte": "a", "fait": False}, {"texte": "b", "fait": False}]}
    assert "plan saved (0/2 done)" in envoyer.messages[1]
    assert types(evs)[-1] == "termine"


def test_done_refuse_si_plan_inacheve():
    evs, envoyer, _ = lancer([bloc(plan("[ ] a"), fini()), bloc(plan("[x] a"), fini())])
    assert "NOT FINISHED: unchecked plan steps: a" in envoyer.messages[1]
    assert "relance_fin" in types(evs) and types(evs)[-1] == "termine"


def test_done_demande_une_verification_une_fois():
    evs, envoyer, _ = lancer([bloc(creer("a.py")), bloc(fini()), bloc(fini())])
    assert "Verify your work first" in envoyer.messages[2]
    assert types(evs).count("relance_fin") == 1 and types(evs)[-1] == "termine"


def test_verification_faite_pas_de_relance():
    reponses = [bloc(creer("a.py"), {"action": "run", "command": "python a.py"}), bloc(fini())]
    evs, _, _ = lancer(reponses)
    assert "relance_fin" not in types(evs) and types(evs)[-1] == "termine"


def test_pas_de_verification_pour_du_texte():
    evs, _, _ = lancer([bloc(creer("notes.md")), bloc(fini())])
    assert "relance_fin" not in types(evs) and types(evs)[-1] == "termine"


def test_relances_bornees():
    evs, _, _ = lancer([bloc(plan("[ ] a"))] + [bloc(fini())] * 3)
    assert types(evs).count("relance_fin") == 2 and types(evs)[-1] == "termine"


def test_done_saute_si_une_action_echoue():
    evs, envoyer, _ = lancer([bloc(creer("x"), fini()), bloc(fini())], FauxExecuteur(echecs={"x"}))
    assert "[2] done: SKIPPED" in envoyer.messages[1]
    assert types(evs).count("termine") == 1


def test_done_pas_en_dernier_saute():
    _, envoyer, ex = lancer([bloc(fini(), creer("a.md")), bloc(fini())])
    assert "[1] done: SKIPPED" in envoyer.messages[1] and len(ex.actions) == 1


def test_ask_met_en_pause():
    tache = EtatTache()
    evs, envoyer, _ = lancer([bloc(plan("[ ] a"), {"action": "ask", "question": "Quel port ?"})], tache=tache)
    assert evs[-1]["type"] == "question" and evs[-1]["question"] == "Quel port ?"
    assert evs[-1]["tache"]["plan"] == [{"texte": "a", "fait": False}]
    assert len(envoyer.messages) == 1


def test_ask_garde_les_resultats_du_lot():
    tache = EtatTache()
    lancer([bloc(LIRE, {"action": "ask", "question": "?"})], tache=tache)
    assert "[1] read a: OK" in tache.resultats_en_attente


def test_format_casse_garde_le_texte():
    evs, envoyer, _ = lancer(["je réfléchis à voix haute"] * 3)
    assert types(evs).count("erreur_format") == 3 and evs[0]["corps"] == "je réfléchis à voix haute"
    assert evs[-1]["type"] == "erreur" and "format" in evs[-1]["corps"]


def test_json_invalide_donne_un_rappel_precis():
    casse = '{"action": "create", "path": "a.py", "content": "x'
    evs, envoyer, _ = lancer([casse, bloc(fini())])
    assert "erreur_format" in types(evs) and "Your JSON is invalid" in envoyer.messages[1]


def test_reponse_sans_action_donne_le_rappel_general():
    _, envoyer, _ = lancer(["je réfléchis encore", bloc(fini())])
    assert "Format not understood" in envoyer.messages[1]


def test_limite_de_tours():
    evs, _, ex = lancer([bloc(LIRE)] * 10, max_tours=5)
    assert types(evs)[-1] == "limite" and len(ex.actions) == 5


def test_erreur_de_gemini_renvoie_le_meme_message():
    # « Sorry, something went wrong » n'est pas une faute de format : on renvoie le message.
    reponses = ["Gemini a dit\nSorry, something went wrong. Please try your request again.", bloc(LIRE), bloc(fini())]
    evs, envoyer, ex = lancer(reponses)
    assert envoyer.messages[:2] == ["tâche", "tâche"]
    assert "erreur_gemini" in types(evs) and "erreur_format" not in types(evs)
    assert len(ex.actions) == 1 and types(evs)[-1] == "termine"


def test_erreur_de_gemini_deux_fois_arrete_clairement():
    erreur = "Sorry, something went wrong. Please try your request again."
    evs, envoyer, _ = lancer([erreur, erreur, bloc(LIRE)])
    assert types(evs)[-1] == "erreur" and "Sorry, something went wrong" in evs[-1]["corps"]
    assert len(envoyer.messages) == 2


def test_ancien_format_termine_accepte():
    evs, _, _ = lancer(["TERMINÉ : c'est fait"])
    assert evs[-1] == {"type": "termine", "resume": "c'est fait"}
