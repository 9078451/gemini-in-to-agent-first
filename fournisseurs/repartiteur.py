"""Quelle file d'attente pour quel fournisseur.

- Un site piloté dans Chrome (Gemini, ChatGPT, Claude.ai) : une `FileAttente` par rôle
  (Chat, Cowork), chacune son onglet et son fil — Playwright l'exige.
- Une API : une `FileParallele` partagée par le Chat et Cowork ; plusieurs demandes
  partent en même temps.

Les files sont créées au premier besoin : un site jamais utilisé n'ouvre aucune fenêtre.
"""
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, TypeVar

from agent_first.file_attente import FileAttente
from pilote.erreurs import ErreurPilote
from pilote.modeles import Pilote

T = TypeVar("T")
journal = logging.getLogger(__name__)
TOUS_ROLES = "*"


class FournisseurInconnu(ErreurPilote):
    def __init__(self, fournisseur: str) -> None:
        self.fournisseur = fournisseur
        super().__init__(f"Fournisseur « {fournisseur} » inconnu ou désactivé (Paramètres → Fournisseurs).")


class FileParallele:
    """Même usage que `FileAttente`, sans fil imposé : les demandes partent en parallèle."""

    def __init__(self, fabrique_pilote: Callable[[], Pilote], fils: int = 8, nom: str = "file-api") -> None:
        self._fabrique = fabrique_pilote
        self._pilote: Pilote | None = None
        self._verrou = threading.Lock()
        self._en_cours = 0
        self._executeur = ThreadPoolExecutor(max_workers=fils, thread_name_prefix=nom)

    def demarrer(self) -> None:
        pass

    def soumettre(self, travail: Callable[[Pilote], T]) -> "Future[T]":
        with self._verrou:
            self._en_cours += 1
        futur = self._executeur.submit(self._executer, travail)
        return futur

    def occupee(self) -> bool:
        with self._verrou:
            return self._en_cours > 0

    def arreter(self) -> None:
        self._executeur.shutdown(wait=False, cancel_futures=True)

    def _executer(self, travail: Callable[[Pilote], T]) -> T:
        try:
            with self._verrou:
                if self._pilote is None:
                    self._pilote = self._fabrique()
                pilote = self._pilote
            return travail(pilote)
        finally:
            with self._verrou:
                self._en_cours -= 1


class Repartiteur:
    """`fabriques[fournisseur](role)` fabrique le pilote d'un fournisseur (appelée dans le fil
    de sa file) ; `paralleles` : les fournisseurs sans fil imposé (API). `existantes` : des
    files déjà créées, par (fournisseur, rôle)."""

    def __init__(
        self,
        fabriques: dict[str, Callable[[str], Pilote]],
        paralleles: set[str],
        existantes: dict[tuple[str, str], object] | None = None,
    ) -> None:
        self._fabriques = fabriques
        self._paralleles = paralleles
        self._files: dict[tuple[str, str], object] = dict(existantes or {})
        self._verrou = threading.Lock()

    @classmethod
    def unique(cls, fournisseur: str, role: str, file) -> "Repartiteur":
        """Une seule file déjà prête (tests, ou une app sans autres fournisseurs)."""
        return cls({}, set(), {(fournisseur, role): file})

    def connait(self, fournisseur: str) -> bool:
        return fournisseur in self._fabriques or any(f == fournisseur for f, _ in self._files)

    def file(self, fournisseur: str, role: str):
        cle = (fournisseur, TOUS_ROLES if fournisseur in self._paralleles else role)
        with self._verrou:
            file = self._files.get(cle)
            if file is None:
                if fournisseur not in self._fabriques:
                    raise FournisseurInconnu(fournisseur)
                fabrique = self._fabriques[fournisseur]
                if fournisseur in self._paralleles:
                    file = FileParallele(lambda: fabrique(role), nom=f"api-{fournisseur}")
                else:
                    file = FileAttente(lambda: fabrique(role), nom=f"file-{fournisseur}-{role}")
                file.demarrer()
                self._files[cle] = file
            return file

    def occupee(self, fournisseur: str, role: str) -> bool:
        cle = (fournisseur, TOUS_ROLES if fournisseur in self._paralleles else role)
        with self._verrou:
            file = self._files.get(cle)
        return file is not None and file.occupee()

    def arreter(self) -> None:
        with self._verrou:
            files = list(self._files.values())
        for file in files:
            try:
                file.arreter()
            except Exception:
                journal.exception("File impossible à arrêter")
