"""Ce que l'app et l'API réseau savent des fournisseurs actifs : leurs modèles, leurs
niveaux, leur état, et le secours à utiliser.

Les listes de modèles sont lues chez chaque fournisseur (Gemini : dans son onglet ; API :
`GET /models`), gardées, et relues sur demande (Paramètres → « Lire la liste »).
"""
import logging
import threading

from fournisseurs.catalogue import API, CATALOGUE, MODELE_SITE, PAR_DEFAUT
from fournisseurs.commun import NIVEAUX
from fournisseurs.etats import EtatsFournisseurs
from fournisseurs.reglages import ReglagesFournisseurs
from fournisseurs.repartiteur import Repartiteur
from pilote.chrome import ONGLET_CHAT
from pilote.modeles import Modes, Option

journal = logging.getLogger(__name__)

MODELES_AFFICHES = 8  # d'une liste lue, tant que l'utilisateur n'a pas choisi les siens


class ServiceFournisseurs:
    def __init__(self, reglages: ReglagesFournisseurs, repartiteur: Repartiteur, cache_gemini=None,
                 etats: EtatsFournisseurs | None = None) -> None:
        self.reglages = reglages
        self.repartiteur = repartiteur
        self.etats = etats or EtatsFournisseurs()
        self._cache_gemini = cache_gemini
        self._lus: dict[str, list[str]] = {}
        self._en_lecture: set[str] = set()
        self._verrou = threading.Lock()

    # ---- qui, quoi --------------------------------------------------------

    def actifs(self) -> list[str]:
        return [f for f in self.reglages.actifs() if self.repartiteur.connait(f)]

    def est_actif(self, fournisseur: str) -> bool:
        return fournisseur in self.actifs()

    @staticmethod
    def nom(fournisseur: str) -> str:
        f = CATALOGUE.get(fournisseur)
        return f.nom if f else fournisseur

    def modes(self, fournisseur: str) -> Modes:
        """Modèles et niveaux proposés (le premier modèle « actif » sert par défaut)."""
        if fournisseur == PAR_DEFAUT and self._cache_gemini is not None:
            return self._cache_gemini.lire()
        f = CATALOGUE[fournisseur]
        choisis = self.reglages.config(fournisseur)["modeles"]
        if f.type == API:
            modeles = choisis or self._lus.get(fournisseur, [])[:MODELES_AFFICHES] or list(f.modeles_suggeres)
            if not choisis and fournisseur not in self._lus:
                self._lire_en_fond(fournisseur)
        else:
            modeles = choisis or [MODELE_SITE]
        options = [Option(m, "", i == 0) for i, m in enumerate(modeles)]
        return Modes(options, list(NIVEAUX) if f.niveaux else [])

    def liste(self) -> list[dict]:
        """Pour le menu des modèles : chaque fournisseur actif, son état, ses modèles et niveaux."""
        sortie = []
        for fournisseur in self.actifs():
            modes = self.modes(fournisseur)
            sortie.append({
                "id": fournisseur, "nom": self.nom(fournisseur), "type": CATALOGUE[fournisseur].type,
                **self.etats.lire(fournisseur),
                "modeles": [{"nom": o.nom, "description": o.description, "actif": o.actif} for o in modes.modeles],
                "niveaux": [{"nom": o.nom, "description": o.description, "actif": o.actif} for o in modes.niveaux],
            })
        return sortie

    def a_des_niveaux(self, fournisseur: str) -> bool:
        return CATALOGUE[fournisseur].niveaux if fournisseur in CATALOGUE else False

    def secours(self) -> dict | None:
        """Le secours réglé, s'il est utilisable : {"fournisseur", "modele"}."""
        s = self.reglages.secours()
        if not s["actif"] or not s["fournisseur"] or not self.est_actif(s["fournisseur"]):
            return None
        return {"fournisseur": s["fournisseur"], "modele": s["modele"]}

    # ---- listes de modèles --------------------------------------------------

    def lire_modeles(self, fournisseur: str, delai: float = 20.0) -> list[str]:
        """Relit la liste chez le fournisseur (dans sa file) ; lève l'erreur du pilote."""
        if fournisseur == PAR_DEFAUT and self._cache_gemini is not None:
            self._cache_gemini.oublier()
            return [o.nom for o in self._cache_gemini.lire().modeles]
        file = self.repartiteur.file(fournisseur, ONGLET_CHAT)
        lus = file.soumettre(lambda pilote: pilote.lister_modeles()).result(timeout=delai)
        with self._verrou:
            self._lus[fournisseur] = lus
        return lus

    def oublier_modeles(self, fournisseur: str) -> None:
        with self._verrou:
            self._lus.pop(fournisseur, None)
        if fournisseur == PAR_DEFAUT and self._cache_gemini is not None:
            self._cache_gemini.oublier()

    def _lire_en_fond(self, fournisseur: str) -> None:
        with self._verrou:
            if fournisseur in self._en_lecture:
                return
            self._en_lecture.add(fournisseur)

        def lire():
            try:
                self.lire_modeles(fournisseur)
            except Exception as e:
                journal.info("Modèles de %s illisibles : %s", self.nom(fournisseur), e)
                with self._verrou:
                    self._lus.setdefault(fournisseur, [])  # pas de nouvel essai à chaque affichage
            finally:
                with self._verrou:
                    self._en_lecture.discard(fournisseur)

        threading.Thread(target=lire, name=f"modeles-{fournisseur}", daemon=True).start()
