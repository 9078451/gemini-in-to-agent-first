"""L'état du compte Google (connecté ou non), gardé en mémoire.

Avant, `/api/etat` le demandait à l'onglet du Chat à chaque appel : derrière une
longue réponse, il faisait la queue (jusqu'à 5 s) en tenant un fil du serveur.
Il est maintenant noté à chaque message, et relu dans l'onglet seulement quand
sa file est libre et qu'il date de plus d'une minute.
"""
import logging
import threading
import time
from typing import Callable

journal = logging.getLogger(__name__)


class EtatGoogle:
    def __init__(self, file, chrome_lance: Callable[[], bool], age_max: float = 60.0,
                 horloge: Callable[[], float] = time.monotonic) -> None:
        self._file = file
        self._chrome_lance = chrome_lance
        self._age_max = age_max
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._valeur: bool | None = None
        self._quand: float | None = None

    def noter(self, connecte: bool | None) -> None:
        with self._verrou:
            self._valeur, self._quand = connecte, self._horloge()

    def lire(self) -> bool | None:
        if not self._chrome_lance():
            return None
        with self._verrou:
            valeur, quand = self._valeur, self._quand
        frais = quand is not None and self._horloge() - quand < self._age_max
        if frais or self._file.occupee():
            return valeur
        try:
            lu = self._file.soumettre(lambda pilote: pilote.est_connecte()).result(timeout=5)
        except Exception:
            journal.debug("État de Google illisible", exc_info=True)
            return valeur
        self.noter(lu)
        return lu
