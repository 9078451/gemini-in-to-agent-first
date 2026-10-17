"""Un seul Chrome : les demandes passent une par une, dans un fil dédié.

Playwright (mode synchrone) doit être utilisé depuis le fil qui l'a créé :
le pilote est donc fabriqué et utilisé uniquement dans le fil de la file.
"""
import logging
import queue
import threading
from concurrent.futures import Future
from typing import Callable, TypeVar

from pilote.erreurs import ErreurPilote
from pilote.modeles import Pilote

T = TypeVar("T")
journal = logging.getLogger(__name__)
_FIN = object()


def rechauffer(file: "FileAttente") -> Future:
    """Prépare Chrome et Gemini en arrière-plan dès le démarrage : le premier message
    n'attend plus l'ouverture de Chrome. Un échec (Google déconnecté…) est seulement noté :
    il se reproduira, avec son message clair, au premier vrai message."""
    futur = file.soumettre(lambda pilote: pilote.preparer())
    futur.add_done_callback(
        lambda f: f.exception() is not None and journal.warning("Gemini pas prêt au démarrage : %s", f.exception())
    )
    return futur


class FileAttente:
    def __init__(self, fabrique_pilote: Callable[[], Pilote]) -> None:
        self._fabrique = fabrique_pilote
        self._pilote: Pilote | None = None
        self._taches: queue.Queue = queue.Queue()
        self._en_attente = 0  # demandes soumises pas encore terminées
        self._verrou = threading.Lock()
        self._fil = threading.Thread(target=self._boucle, name="file-gemini", daemon=True)

    def demarrer(self) -> None:
        self._fil.start()

    def arreter(self) -> None:
        self._taches.put(_FIN)
        self._fil.join(timeout=10)

    def soumettre(self, travail: Callable[[Pilote], T]) -> "Future[T]":
        futur: Future = Future()
        with self._verrou:
            self._en_attente += 1
        self._taches.put((travail, futur))
        return futur

    def occupee(self) -> bool:
        """Une demande tourne ou attend son tour (une tâche Cowork peut durer des minutes)."""
        with self._verrou:
            return self._en_attente > 0

    def _boucle(self) -> None:
        while True:
            element = self._taches.get()
            if element is _FIN:
                return
            travail, futur = element
            try:
                self._executer(travail, futur)
            finally:
                with self._verrou:
                    self._en_attente -= 1

    def _executer(self, travail: Callable[[Pilote], T], futur: Future) -> None:
        if not futur.set_running_or_notify_cancel():
            return
        try:
            if self._pilote is None:
                self._pilote = self._fabrique()
            futur.set_result(travail(self._pilote))
        except ErreurPilote as e:
            journal.warning("Demande à Gemini échouée : %s", e)
            futur.set_exception(e)
        except Exception as e:
            journal.exception("Erreur inattendue dans la file d'attente")
            futur.set_exception(e)
