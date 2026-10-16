"""Le service Cowork : lance la boucle d'agent, pousse les étapes en direct (SSE)
et gère l'accord de l'utilisateur pour les actions dangereuses.

Une seule tâche Cowork à la fois (un seul Chrome dédié, sérialisé par la file).
"""
import json
import logging
import queue
import threading
from pathlib import Path
from typing import Callable, Iterator

from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from cowork import boucle
from cowork.actions import Executeur
from cowork.format import Action
from cowork.instructions import premier_message
from cowork.surete import classer

journal = logging.getLogger(__name__)


class _Arret(Exception):
    pass


class _Session:
    def __init__(self) -> None:
        self.file: queue.Queue = queue.Queue()
        self.accord = threading.Event()
        self.reponse_accord = False
        self.action_en_attente = ""
        self.toujours: set[str] = set()
        self.arret = threading.Event()
        self.etape = 0


class ServiceCowork:
    def __init__(
        self,
        file: FileAttente,
        historique: Historique,
        fabrique_executeur: Callable[[Path], Executeur],
        max_etapes: int,
        echecs_max: int,
        taille_max: int,
    ) -> None:
        self._file = file
        self._historique = historique
        self._fabrique = fabrique_executeur
        self._max_etapes = max_etapes
        self._echecs_max = echecs_max
        self._taille_max = taille_max
        self._sessions: dict[str, _Session] = {}

    def demarrer(
        self, conversation_id: str, dossier: str, adresse: str | None, texte: str, modele, niveau
    ) -> None:
        session = _Session()
        self._sessions[conversation_id] = session
        executeur = self._fabrique(Path(dossier))
        message = premier_message(Path(dossier), texte) if adresse is None else texte
        # Le message « toi » est déjà enregistré par la route (titre + bulle à la réouverture).

        def travail(pilote) -> None:
            etat = {"adresse": adresse}

            def envoyer(msg: str) -> str:
                if session.arret.is_set():
                    raise _Arret()
                resultat = pilote.envoyer(etat["adresse"], msg, modele, niveau)
                etat["adresse"] = resultat.adresse
                if etat["adresse"]:
                    self._historique.enregistrer_adresse(conversation_id, etat["adresse"])
                return resultat.reponse

            try:
                boucle.executer(
                    envoyer=envoyer,
                    message_initial=message,
                    executer=executeur.executer,
                    classer=classer,
                    demander_accord=lambda action, raison: self._demander(session, action),
                    emettre=lambda ev: self._emettre(conversation_id, session, ev),
                    max_etapes=self._max_etapes,
                    echecs_max=self._echecs_max,
                    taille_max=self._taille_max,
                )
            except _Arret:
                self._emettre(conversation_id, session, {"type": "arret"})
            except Exception as e:
                journal.exception("Erreur dans la tâche Cowork")
                self._emettre(conversation_id, session, {"type": "erreur", "corps": str(e)})
            finally:
                session.file.put(None)  # fin du flux

        self._file.soumettre(travail)

    def flux(self, conversation_id: str) -> Iterator[str]:
        session = self._sessions.get(conversation_id)
        if session is None:
            return
        while True:
            evenement = session.file.get()
            if evenement is None:
                return
            yield f"data: {json.dumps(evenement, ensure_ascii=False)}\n\n"

    def decider(self, conversation_id: str, etape: int, reponse: str, toujours: bool) -> None:
        session = self._sessions.get(conversation_id)
        if session is None:
            return
        session.reponse_accord = reponse == "continuer"
        if toujours and session.reponse_accord:
            session.toujours.add(session.action_en_attente)
        session.accord.set()

    def arreter(self, conversation_id: str) -> None:
        session = self._sessions.get(conversation_id)
        if session is None:
            return
        session.arret.set()
        session.accord.set()  # débloque un accord en attente

    def _demander(self, session: _Session, action: Action) -> bool:
        if action.nom in session.toujours:
            return True
        session.action_en_attente = action.nom
        session.accord.clear()
        session.accord.wait()
        if session.arret.is_set():
            return False
        return session.reponse_accord

    def _emettre(self, conversation_id: str, session: _Session, evenement: dict) -> None:
        evenement = {**evenement, "etape": session.etape}
        session.etape += 1
        try:
            self._historique.ajouter_etape(conversation_id, evenement)
        except Exception:
            journal.exception("Étape Cowork non enregistrée")
        session.file.put(evenement)
