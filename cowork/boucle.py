"""La boucle d'agent : envoyer à Gemini, lire son lot d'actions, l'exécuter (avec
l'accord de l'utilisateur si besoin), lui renvoyer les résultats… jusqu'à une fin
acceptée, une question, ou la limite de tours.

La fin est contrôlée : un « done » est refusé tant que le plan a des étapes non
cochées, ou si du code a été écrit sans être vérifié (une fois). La boucle ne
connaît ni le pilote, ni le réseau, ni les fils : tout passe par les branchements.
"""
import time
from dataclasses import dataclass
from typing import Callable

from cowork.catalogue import Action, Resultat, valider
from cowork.format import LigneResultat, est_erreur_gemini, formater_resultats, lire_actions, rappel_pour
from cowork.surete import Verdict
from cowork.tache import EtatTache, lire_plan

# Quand Gemini répond par sa propre erreur, le même message est renvoyé une fois.
ESSAIS_SI_ERREUR_GEMINI = 2
EXTRAIT_MAX = 2000  # caractères gardés d'une réponse hors format, pour l'afficher
FINS = ("ask", "done")
VERIFIER = (
    "Verify your work first (run it, test it, or start + visit a server). "
    "If verification makes no sense here, send done again."
)


@dataclass(frozen=True)
class Reglages:
    max_tours: int
    max_actions: int
    echecs_max: int
    taille_max: int
    taille_max_message: int
    relances_fin_max: int


@dataclass(frozen=True)
class Branchements:
    envoyer: Callable[[str], str]
    executer: Callable[[Action], Resultat]
    classer: Callable[[Action], Verdict]
    demander_accord: Callable[[Action, str], bool]
    emettre: Callable[[dict], None]
    doit_arreter: Callable[[], bool] = lambda: False  # « Arrêter » coupe aussi un lot en cours


def executer_tache(
    message: str, tache: EtatTache, b: Branchements, r: Reglages, horloge: Callable[[], float] = time.monotonic
) -> None:
    echecs = 0
    for _ in range(r.max_tours):
        debut = horloge()
        reponse = _envoyer(b, message)
        if reponse is None:
            return
        duree = horloge() - debut  # ce que l'utilisateur attend : la réflexion et l'écriture de Gemini
        tache.temps_gemini += duree
        b.emettre({"type": "tour", "gemini": round(duree, 1)})
        actions = lire_actions(reponse)
        if not actions:
            b.emettre({"type": "erreur_format", "corps": _extrait(reponse)})
            echecs += 1
            if echecs >= r.echecs_max:
                b.emettre({"type": "erreur", "corps": f"Gemini n'a pas respecté le format {echecs} fois de suite : tâche arrêtée."})
                return
            message = rappel_pour(reponse)
            continue
        echecs = 0
        suite = _traiter_lot(actions, tache, b, r, horloge)
        if suite is None:
            return
        message = suite
    b.emettre({"type": "limite"})


def _envoyer(b: Branchements, message: str) -> str | None:
    """La réponse de Gemini ; None (et une erreur émise) s'il plante deux fois de suite."""
    reponse = b.envoyer(message)
    for _ in range(ESSAIS_SI_ERREUR_GEMINI - 1):
        if not est_erreur_gemini(reponse):
            return reponse
        b.emettre({"type": "erreur_gemini", "corps": reponse.strip()})
        reponse = b.envoyer(message)
    if est_erreur_gemini(reponse):
        erreur = reponse.replace("Gemini a dit", "", 1).strip() or "réponse vide"
        b.emettre({"type": "erreur", "corps": f"Gemini a répondu par une erreur deux fois de suite : « {erreur} ». Réessaie dans un moment."})
        return None
    return reponse


def _extrait(reponse: str) -> str:
    texte = reponse.replace("Gemini a dit", "", 1).strip()
    return texte if len(texte) <= EXTRAIT_MAX else texte[:EXTRAIT_MAX] + "…"


def _traiter_lot(
    actions: list[Action], tache: EtatTache, b: Branchements, r: Reglages, horloge: Callable[[], float]
) -> str | None:
    """Exécute un lot ; renvoie le message de résultats à envoyer, ou None si la tâche
    s'arrête (fin acceptée ou question)."""
    notes = []
    if len(actions) > r.max_actions:
        notes.append(f"Only the first {r.max_actions} actions were run; send the rest in your next message.")
        actions = actions[: r.max_actions]
    lignes: list[LigneResultat] = []
    echec, raison_saut = False, "an earlier action failed"
    for rang, action in enumerate(actions, 1):
        dernier = rang == len(actions)
        if not echec and b.doit_arreter():
            echec, raison_saut = True, "stopped by the user"
        if echec:
            _sauter(b, lignes, rang, action, raison_saut)
            continue
        erreur = valider(action)
        if erreur:
            b.emettre({"type": "action", "action": action.nom, "champs": action.champs})
            b.emettre({"type": "resultat", "ok": False, "corps": erreur, "diff": None, "code": None})
            lignes.append(LigneResultat(rang, action, "ERROR", erreur))
            echec = True
        elif action.nom in FINS and not dernier:
            _sauter(b, lignes, rang, action, f'"{action.nom}" must be the last action of a message')
        elif action.nom == "ask":
            tache.resultats_en_attente = formater_resultats(lignes, r.taille_max, r.taille_max_message) if lignes else ""
            b.emettre({"type": "question", "question": action.champs["question"], "tache": tache.vers_dict()})
            return None
        elif action.nom == "done":
            refus = _refus_de_fin(tache, r)
            if refus is None:
                b.emettre({"type": "termine", "resume": action.champs["summary"]})
                return None
            b.emettre({"type": "relance_fin", "raison": refus})
            lignes.append(LigneResultat(rang, action, "NOT ACCEPTED", ""))
            notes.append(refus)
        elif action.nom == "plan":
            tache.plan = lire_plan(action.champs["steps"])
            b.emettre({"type": "plan", "etapes": tache.plan})
            faites = sum(e["fait"] for e in tache.plan)
            lignes.append(LigneResultat(rang, action, "OK", f"plan saved ({faites}/{len(tache.plan)} done)"))
        else:
            echec = not _executer(action, rang, lignes, tache, b, horloge)
    return formater_resultats(lignes, r.taille_max, r.taille_max_message, "\n".join(notes))


def _sauter(b: Branchements, lignes: list[LigneResultat], rang: int, action: Action, raison: str) -> None:
    b.emettre({"type": "saute", "action": action.nom, "champs": action.champs})
    lignes.append(LigneResultat(rang, action, "SKIPPED", raison))


def _executer(
    action: Action, rang: int, lignes: list[LigneResultat], tache: EtatTache, b: Branchements, horloge: Callable[[], float]
) -> bool:
    """Exécute une action (accord compris) ; True si elle a réussi."""
    b.emettre({"type": "action", "action": action.nom, "champs": action.champs})
    verdict = b.classer(action)
    if verdict.dangereuse:
        b.emettre({"type": "demande", "action": action.nom, "raison": verdict.raison})
        if not b.demander_accord(action, verdict.raison):
            b.emettre({"type": "refus"})
            lignes.append(LigneResultat(rang, action, "ERROR", "refused by the user; find another way"))
            return False
    debut = horloge()
    resultat = b.executer(action)
    tache.temps_actions += horloge() - debut
    tache.noter(action, resultat)
    b.emettre({"type": "resultat", "ok": resultat.ok, "corps": resultat.corps, "diff": resultat.diff, "code": resultat.code})
    if resultat.ok:
        statut = "OK"
    elif resultat.code not in (None, 0):
        statut = f"ERROR (exit code {resultat.code})"
    else:
        statut = "ERROR"
    lignes.append(LigneResultat(rang, action, statut, resultat.corps))
    return resultat.ok


def _refus_de_fin(tache: EtatTache, r: Reglages) -> str | None:
    """La raison de refuser un « done », ou None pour l'accepter."""
    if tache.relances >= r.relances_fin_max:
        return None
    restantes = tache.etapes_restantes()
    if restantes:
        refus = (
            f"NOT FINISHED: unchecked plan steps: {'; '.join(restantes)}. "
            "Continue, or send the plan again without them if they are no longer needed."
        )
    elif tache.ecrit_depuis_verif and not tache.verif_demandee:
        tache.verif_demandee = True
        refus = VERIFIER
    else:
        return None
    tache.relances += 1
    return refus
