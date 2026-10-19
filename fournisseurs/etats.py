"""L'état de chaque fournisseur, noté à chaque réponse ou erreur : la barre latérale et le
menu des modèles l'affichent sans rien demander au fournisseur.

prêt · limite (quota atteint, avec l'heure si le site la donne) · déconnecté (compte ou
clé) · panne · inconnu. Une limite ou une panne s'efface d'elle-même après un moment :
le fournisseur redevient « inconnu » et sera réessayé.
"""
import re
import threading
import time
from typing import Callable

from pilote.erreurs import (
    ChoixBloque, CleRefusee, LimiteFournisseur, LimiteGemini, LimiteSite, PasConnecteGoogle, PasConnecteSite,
    VerificationGoogle,
)

PRET, LIMITE, DECONNECTE, PANNE, INCONNU = "pret", "limite", "deconnecte", "panne", "inconnu"
OUBLI = {LIMITE: 30 * 60.0, PANNE: 10 * 60.0}  # s avant de redevenir « inconnu »
HEURE = re.compile(r"\b(\d{1,2}[:h]\d{2}(?:\s?[AP]M)?)", re.IGNORECASE)


def classer(erreur: Exception) -> str | None:
    """L'état qu'une erreur révèle, ou None si elle ne dit rien du fournisseur
    (modèle introuvable, arrêt demandé…)."""
    if isinstance(erreur, (LimiteGemini, ChoixBloque, LimiteFournisseur, LimiteSite)):
        return LIMITE
    if isinstance(erreur, (PasConnecteGoogle, PasConnecteSite, VerificationGoogle, CleRefusee)):
        return DECONNECTE
    if getattr(erreur, "secours", False):
        return PANNE
    return None


class EtatsFournisseurs:
    def __init__(self, horloge: Callable[[], float] = time.monotonic) -> None:
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._etats: dict[str, tuple[str, str | None, float]] = {}

    def noter_ok(self, fournisseur: str) -> None:
        with self._verrou:
            self._etats[fournisseur] = (PRET, None, self._horloge())

    def noter_erreur(self, fournisseur: str, erreur: Exception) -> None:
        etat = classer(erreur)
        if etat is None:
            return
        detail = str(erreur)
        if etat == LIMITE:
            heure = HEURE.search(detail)
            detail = f"jusqu'à {heure.group(1)}" if heure else "quota atteint"
        with self._verrou:
            self._etats[fournisseur] = (etat, detail, self._horloge())

    def lire(self, fournisseur: str) -> dict:
        with self._verrou:
            etat, detail, quand = self._etats.get(fournisseur, (INCONNU, None, 0.0))
        if etat in OUBLI and self._horloge() - quand > OUBLI[etat]:
            etat, detail = INCONNU, None
        return {"etat": etat, "detail": detail}

    def tous(self, fournisseurs: list[str]) -> dict[str, dict]:
        return {f: self.lire(f) for f in fournisseurs}
