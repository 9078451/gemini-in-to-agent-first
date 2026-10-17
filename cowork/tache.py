"""L'état d'une tâche Cowork : son plan, ce qu'elle a vraiment fait, et ce qu'il
faut pour accepter sa fin.

Une tâche va de la demande de l'utilisateur au « done » accepté. Une question de
Gemini (`ask`) la met en pause : l'état est alors gardé (`vers_dict`) pour la
reprendre à la réponse, même après un redémarrage d'Agent First.
"""
import os
import posixpath
import re
from dataclasses import asdict, dataclass, field, fields

from cowork.catalogue import Action, Resultat

_CASE = re.compile(r"^(?:[-*]\s*)?\[([ xX✓])\]\s*(.*)$")
EXTENSIONS_TEXTE = (".md", ".txt")  # en écrire ne demande pas de vérification
VERIFICATIONS = {"run", "start", "visit"}


def lire_plan(steps) -> list[dict]:
    """« [x] a » / « [ ] b » → [{"texte": "a", "fait": True}, …] ; une liste ou un texte multi-lignes."""
    lignes = steps if isinstance(steps, list) else str(steps).splitlines()
    plan = []
    for brute in lignes:
        texte = str(brute).strip()
        if not texte:
            continue
        case = _CASE.match(texte)
        if case:
            plan.append({"texte": case.group(2).strip(), "fait": case.group(1) != " "})
        else:
            plan.append({"texte": texte, "fait": False})
    return plan


@dataclass
class EtatTache:
    plan: list[dict] = field(default_factory=list)
    effets: list[list[str]] = field(default_factory=list)  # [["cree" | "modifie" | "supprime", chemin], …]
    commandes: list[dict] = field(default_factory=list)  # [{"texte": …, "code": …}, …]
    ecrit_depuis_verif: bool = False
    verif_demandee: bool = False
    relances: int = 0
    verifications: int = 0
    resultats_en_attente: str = ""  # résultats d'un lot interrompu par une question, à renvoyer à Gemini
    temps_gemini: float = 0.0  # secondes passées à attendre les réponses de Gemini
    temps_actions: float = 0.0  # secondes passées à exécuter les actions (sans les accords)

    def noter(self, action: Action, resultat: Resultat) -> None:
        if action.nom in VERIFICATIONS:
            self.verifications += 1
            self.ecrit_depuis_verif = False
            if action.nom in ("run", "start"):
                self.commandes.append({"texte": action.champs.get("command", ""), "code": resultat.code})
        if resultat.ok and resultat.effet:
            self.effets.append(list(resultat.effet))
            if not resultat.effet[1].lower().endswith(EXTENSIONS_TEXTE):
                self.ecrit_depuis_verif = True

    def etapes_restantes(self) -> list[str]:
        return [etape["texte"] for etape in self.plan if not etape["fait"]]

    def bilan(self, processus: list[dict]) -> dict:
        # Un fichier par clé (« ./a.py », « a.py » et, sous Windows, « A.py » sont le même),
        # montré sous le premier chemin vu ; les dict gardent l'ordre d'arrivée.
        crees, modifies, supprimes = {}, {}, {}
        for effet, brut in self.effets:
            chemin = posixpath.normpath(brut.replace("\\", "/"))
            cle = os.path.normcase(chemin)
            if effet == "cree":
                supprimes.pop(cle, None)
                crees.setdefault(cle, chemin)
            elif effet == "modifie":
                if cle not in crees:
                    modifies.setdefault(cle, chemin)
            elif cle in crees:  # créé puis supprimé dans la même tâche : il n'en reste rien
                del crees[cle]
            else:
                modifies.pop(cle, None)
                supprimes.setdefault(cle, chemin)
        return {
            "crees": list(crees.values()),
            "modifies": list(modifies.values()),
            "supprimes": list(supprimes.values()),
            "commandes": list(self.commandes),
            "verifications": self.verifications,
            "plan_inacheve": self.etapes_restantes(),
            "processus": [p for p in processus if p.get("actif")],
            "temps": {"gemini": round(self.temps_gemini, 1), "actions": round(self.temps_actions, 1)},
        }

    def vers_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def depuis_dict(cls, donnees: dict) -> "EtatTache":
        connus = {f.name for f in fields(cls)}
        return cls(**{cle: valeur for cle, valeur in donnees.items() if cle in connus})
