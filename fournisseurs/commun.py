"""Ce que les pilotes par API partagent : niveaux de réflexion, modèle par défaut,
écriture au fil de l'eau."""
import time
from typing import Callable

from fournisseurs.catalogue import CATALOGUE
from fournisseurs.markdown import markdown_vers_html
from fournisseurs.reglages import ReglagesFournisseurs
from pilote.erreurs import DemandeRefusee
from pilote.modeles import Option

# Les mêmes noms que Gemini : l'app n'a qu'un menu « Réflexion ».
EFFORTS = {"Min.": "low", "Moyen": "medium", "Max.": "high"}
NIVEAUX = [Option("Min.", "Rapide et efficace"), Option("Moyen", "Équilibré", True), Option("Max.", "Très poussé")]
RENDU_MIN = 0.12  # s entre deux rendus HTML d'une réponse qui s'écrit


def modele_choisi(fournisseur: str, reglages: ReglagesFournisseurs, modele: str | None,
                  lus: list[str] | None = None) -> str:
    """Le modèle demandé, sinon le premier choisi dans Paramètres, lu chez le fournisseur ou suggéré."""
    for candidat in (modele, *reglages.config(fournisseur)["modeles"][:1], *(lus or [])[:1],
                     *CATALOGUE[fournisseur].modeles_suggeres[:1]):
        if candidat:
            return candidat
    raise DemandeRefusee(CATALOGUE[fournisseur].nom, "aucun modèle choisi : ouvre Paramètres → Fournisseurs.")


class Ecriture:
    """Une réponse qui arrive par morceaux. `au_fil(texte, html)` est appelé à chaque morceau
    (il peut lever `Interrompu`) ; le HTML n'est refait qu'au plus toutes les 0,12 s."""

    def __init__(self, au_fil: Callable[[str, str], None] | None, horloge: Callable[[], float] = time.monotonic) -> None:
        self._au_fil = au_fil
        self._horloge = horloge
        self.texte = ""
        self.html = ""
        self._rendu = -RENDU_MIN

    def ajouter(self, morceau: str) -> None:
        self.texte += morceau
        if self._au_fil is None:
            return
        maintenant = self._horloge()
        if maintenant - self._rendu >= RENDU_MIN:
            self.html, self._rendu = markdown_vers_html(self.texte), maintenant
        self._au_fil(self.texte, self.html)

    def verifier(self) -> None:
        """Rien de nouveau (réflexion, signal de maintien) : un arrêt demandé est quand même vu."""
        if self._au_fil is not None:
            self._au_fil(self.texte, self.html)

    def html_final(self) -> str:
        return markdown_vers_html(self.texte)
