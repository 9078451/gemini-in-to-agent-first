"""Un flux d'évènements pour toute l'app : une demande d'accord d'une tâche que
l'app n'affiche pas (lancée par l'API réseau, ou dans une autre conversation) doit
quand même se voir. Chaque abonné a sa file ; un abonné trop lent perd des
évènements plutôt que de bloquer une tâche Cowork.
"""
import json
import queue
import threading
from typing import Iterator

ATTENTE_PING = 15.0  # s : un commentaire SSE régulier garde la connexion et révèle un navigateur parti


class Diffuseur:
    def __init__(self, taille_file: int = 200) -> None:
        self._taille = taille_file
        self._abonnes: set[queue.Queue] = set()
        self._verrou = threading.Lock()

    def abonner(self) -> queue.Queue:
        file: queue.Queue = queue.Queue(maxsize=self._taille)
        with self._verrou:
            self._abonnes.add(file)
        return file

    def desabonner(self, file: queue.Queue) -> None:
        with self._verrou:
            self._abonnes.discard(file)

    def publier(self, evenement: dict) -> None:
        with self._verrou:
            abonnes = list(self._abonnes)
        for file in abonnes:
            try:
                file.put_nowait(evenement)
            except queue.Full:
                pass  # abonné qui ne lit plus : il rattrapera en rechargeant

    def flux(self) -> Iterator[str]:
        file = self.abonner()
        try:
            while True:
                try:
                    evenement = file.get(timeout=ATTENTE_PING)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(evenement, ensure_ascii=False)}\n\n"
        finally:
            self.desabonner(file)
