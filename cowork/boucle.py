"""La boucle d'agent : enchaîner « action → exécution (ou accord) → résultat »
avec Gemini, jusqu'à « TERMINÉ » ou la limite d'étapes.

La boucle ne connaît ni le pilote, ni le réseau, ni les fils : tout passe par
les fonctions qu'on lui donne, ce qui la rend simple à tester.
"""
from typing import Callable

from cowork.actions import Resultat
from cowork.format import Action, est_erreur_gemini, est_termine, formater_resultat, lire_action, rappel_pour

# Quand Gemini répond par sa propre erreur, le même message est renvoyé une fois.
ESSAIS_SI_ERREUR_GEMINI = 2


def executer(
    envoyer: Callable[[str], str],
    message_initial: str,
    executer: Callable[[Action], Resultat],
    classer: Callable[[Action], "object"],
    demander_accord: Callable[[Action, str], bool],
    emettre: Callable[[dict], None],
    max_etapes: int,
    echecs_max: int,
    taille_max: int,
) -> None:
    message = message_initial
    echecs = 0
    for _ in range(max_etapes):
        reponse = envoyer(message)
        for _ in range(ESSAIS_SI_ERREUR_GEMINI - 1):
            if not est_erreur_gemini(reponse):
                break
            emettre({"type": "erreur_gemini", "corps": reponse.strip()})
            reponse = envoyer(message)
        if est_erreur_gemini(reponse):
            erreur = reponse.replace("Gemini a dit", "", 1).strip() or "réponse vide"
            emettre({"type": "erreur", "corps": f"Gemini a répondu par une erreur deux fois de suite : « {erreur} ». Réessaie dans un moment."})
            return
        action = lire_action(reponse)
        if action is None:
            if est_termine(reponse):
                emettre({"type": "termine", "resume": reponse.strip()})
                return
            emettre({"type": "erreur_format"})
            echecs += 1
            if echecs >= echecs_max:
                emettre({"type": "termine", "resume": "Format non compris, arrêt."})
                return
            message = rappel_pour(reponse)
            continue
        echecs = 0
        emettre({"type": "action", "action": action.nom, "champs": action.champs})
        verdict = classer(action)
        if verdict.dangereuse:
            emettre({"type": "demande", "action": action.nom, "raison": verdict.raison})
            if not demander_accord(action, verdict.raison):
                emettre({"type": "refus"})
                message = formater_resultat(False, "Action refusée par l'utilisateur.")
                continue
        resultat = executer(action)
        emettre({"type": "resultat", "ok": resultat.ok, "corps": resultat.corps, "diff": resultat.diff})
        message = formater_resultat(resultat.ok, resultat.corps[:taille_max])
    emettre({"type": "limite"})
