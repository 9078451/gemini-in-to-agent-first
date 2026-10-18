"""Le service Cowork : lance les tâches, tient leur journal d'évènements (rejouable,
plusieurs lecteurs : l'app, l'API réseau), gère l'accord de l'utilisateur et les
processus en arrière-plan de chaque conversation.

Chaque demande part avec le cadre complet (rôle, actions, dossier, processus,
dernière tâche) : sans ce rappel, Gemini redevenait un chat dès le 2ᵉ message.
Les tâches passent une par une dans l'onglet Gemini de Cowork (sa file) ; le Chat et
l'API ont leur propre onglet et répondent pendant ce temps.
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from agent_first.diffuseur import Diffuseur
from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from cowork.actions import Executeur
from cowork.boucle import Branchements, Reglages, executer_tache
from cowork.catalogue import Action, Resultat
from cowork.instructions import arborescence, cadre
from cowork.processus import GestionnaireProcessus
from cowork.surete import classer
from cowork.tache import EtatTache

journal = logging.getLogger(__name__)
T = TypeVar("T")

FINS = {"termine", "limite", "arret", "erreur"}  # une tâche finie
PAUSES = FINS | {"question"}  # la tâche rend la main à l'utilisateur
NON_ENREGISTRES = {"statut", "processus"}  # passagers : ni dans l'historique, ni rejoués à la réouverture
STATUT_APRES = {
    "demande": "waiting_approval",
    "termine": "done",
    "question": "question",
    "erreur": "error",
    "arret": "stopped",
    "limite": "stopped",
}
SESSIONS_GARDEES = 20  # tâches finies gardées en mémoire (rejouer, état pour l'API)
LIBELLE_FIN = {
    "termine": "done", "limite": "stopped (round limit)", "arret": "stopped", "erreur": "error", "question": "asked a question",
}
TACHES_RESUMEES = 10  # demandes précédentes résumées quand une conversation Gemini neuve démarre


class TacheEnCours(Exception):
    """Une tâche tourne déjà dans cette conversation."""


class _Arret(Exception):
    pass


class _Session:
    def __init__(self) -> None:
        self.evenements: list[dict] = []
        self.condition = threading.Condition()  # protège evenements/fini/statut ; réveille les lecteurs
        self.fini = False
        self.statut = "queued"
        self.tache = EtatTache()
        self.accord = threading.Event()
        self.reponse_accord = False
        self.action_en_attente = ""
        self.etape_en_attente: int | None = None  # n° de la demande d'accord ouverte
        self.arret = threading.Event()
        self.raison_arret = ""


class ServiceCowork:
    def __init__(
        self,
        file: FileAttente,
        historique: Historique,
        fabrique_executeur: Callable[[Path, GestionnaireProcessus, threading.Event], Executeur],
        reglages: Reglages,
        fabrique_processus: Callable[[Path, Callable[[list[dict]], None]], GestionnaireProcessus],
        delai_accord: float = 600.0,
        delai_reponse: float | None = None,
        diffuseur: Diffuseur | None = None,
        max_entrees: int = 150,
        tours_max: int = 30,
        files: dict[str, FileAttente] | None = None,
    ) -> None:
        self._file = file
        # Les tâches d'une conversation confiée à un autre assistant (ChatGPT, Claude…) passent par sa file.
        self._files = files or {}
        self._historique = historique
        self._fabrique_executeur = fabrique_executeur
        self._reglages = reglages
        self._fabrique_processus = fabrique_processus
        # La tâche tourne dans la file de Cowork : un accord jamais donné (fenêtre fermée…)
        # bloquerait les tâches suivantes. Passé ce délai, la tâche s'arrête.
        self._delai_accord = delai_accord
        # Limite par message à Gemini (None = celle du pilote) : 4 Argon peut réfléchir
        # plusieurs minutes avant d'écrire, plus longtemps que la limite du Chat.
        self._delai_reponse = delai_reponse
        self._diffuseur = diffuseur
        self._max_entrees = max_entrees
        # Au-delà de ce nombre de messages, une conversation Gemini ralentit et dérive :
        # la demande suivante part dans une conversation neuve, avec un résumé.
        self._tours_max = tours_max
        self._sessions: dict[str, _Session] = {}
        self._processus: dict[str, GestionnaireProcessus] = {}
        self._verrou = threading.Lock()
        # Types d'action autorisés « toujours » : valent pour toute la conversation.
        self._toujours: dict[str, set[str]] = {}

    # ---- lancer une tâche -----------------------------------------------

    def demarrer(
        self, conversation_id: str, dossier: str, adresse: str | None, texte: str, modele, niveau,
        fournisseur: str = "gemini",
    ) -> None:
        """Lance la tâche et enregistre le message de l'utilisateur, une fois la conversation
        réservée : refusé (TacheEnCours), il ne laisse rien dans l'historique."""
        with self._verrou:
            ancienne = self._sessions.get(conversation_id)
            if ancienne is not None and not ancienne.fini:
                raise TacheEnCours(conversation_id)
            session = _Session()
            self._sessions[conversation_id] = session
            self._ranger()
        try:
            self._historique.ajouter_message(conversation_id, "toi", texte)
        except Exception:
            self._finir(session)  # conversation supprimée entre-temps : rien à lancer
            raise
        self._emettre(conversation_id, session, {"type": "statut", "statut": "queued"})

        def travail(pilote) -> None:
            etat = {"adresse": adresse}

            def envoyer(msg: str) -> str:
                if session.arret.is_set():
                    raise _Arret()
                resultat = pilote.envoyer(etat["adresse"], msg, modele, niveau, delai=self._delai_reponse)
                self._historique.compter_tour(conversation_id)
                etat["adresse"] = resultat.adresse
                if etat["adresse"]:
                    self._historique.enregistrer_adresse(conversation_id, etat["adresse"])
                return resultat.reponse

            self._emettre(conversation_id, session, {"type": "statut", "statut": "running"})
            try:
                # Préparée à son début réel, pas à sa mise en file : la tâche a pu attendre son
                # tour derrière une autre, le dossier et les processus ont pu changer entre-temps.
                dossier_travail = Path(dossier)
                processus = self._processus_de(conversation_id, dossier_travail)
                executeur = self._fabrique_executeur(dossier_travail, processus, session.arret)
                session.tache, message, relais = self._preparer(conversation_id, dossier_travail, texte, processus)
                if relais:
                    etat["adresse"] = None
                    self._historique.repartir(conversation_id)
                    self._emettre(conversation_id, session, {
                        "type": "relais",
                        "corps": f"l'ancienne avait {relais} messages : Gemini reçoit le résumé des demandes précédentes",
                    })
            except Exception as e:  # sans cela, la conversation restait « en cours » (409) jusqu'au redémarrage
                journal.exception("Tâche Cowork impossible à préparer")
                self._emettre(conversation_id, session, {"type": "erreur", "corps": f"Impossible de préparer la tâche : {e}"})
                self._finir(session)
                return
            try:
                executer_tache(
                    message,
                    session.tache,
                    Branchements(
                        envoyer=envoyer,
                        executer=executeur.executer,
                        classer=classer,
                        demander_accord=lambda action, raison: self._demander(conversation_id, session, action),
                        emettre=lambda ev: self._emettre(conversation_id, session, ev),
                        doit_arreter=session.arret.is_set,
                    ),
                    self._reglages,
                )
            except _Arret:
                arret = {"type": "arret", "raison": session.raison_arret} if session.raison_arret else {"type": "arret"}
                self._emettre(conversation_id, session, arret)
            except Exception as e:
                journal.exception("Erreur dans la tâche Cowork")
                self._emettre(conversation_id, session, {"type": "erreur", "corps": str(e)})
            finally:
                self._finir(session)

        self._files.get(fournisseur, self._file).soumettre(travail)

    def _preparer(
        self, conversation_id: str, dossier: Path, texte: str, processus: GestionnaireProcessus
    ) -> tuple[EtatTache, str, int]:
        """L'état de la tâche (repris après une question), le message à envoyer à Gemini, et
        s'il faut une conversation Gemini neuve : le nombre de messages de l'ancienne, ou 0."""
        pause = self._historique.derniere_etape(conversation_id, PAUSES)
        reprise = pause is not None and pause["type"] == "question"
        tache = EtatTache.depuis_dict(pause.get("tache", {})) if reprise else EtatTache()
        conversation = self._historique.conversation(conversation_id)
        # Jamais au milieu d'une question : Gemini doit garder le fil pour comprendre la réponse.
        longue = not reprise and conversation.adresse is not None and conversation.tours_gemini >= self._tours_max
        relais = conversation.tours_gemini if longue else 0
        contenu, entrees = arborescence(dossier, self._max_entrees)
        message = cadre(
            dossier,
            texte,
            contenu=contenu,
            entrees=entrees,
            processus=_processus_actifs(processus.liste()),
            derniere_tache=_derniere_tache(self._historique.derniere_etape(conversation_id, FINS)),
            reponse=reprise,
            max_actions=self._reglages.max_actions,
            conversation=self._resume_conversation(conversation_id) if relais else "",
        )
        if tache.resultats_en_attente:  # les actions d'avant la question : Gemini n'en a pas vu le résultat
            message = f"{tache.resultats_en_attente}\n\n{message}"
            tache.resultats_en_attente = ""
        return tache, message, relais

    def _resume_conversation(self, conversation_id: str) -> str:
        """Les demandes précédentes et leur issue, pour une conversation Gemini neuve."""
        taches: list[list] = []  # [demande, évènement de fin]
        for message in self._historique.messages(conversation_id):
            if message.role == "toi":
                taches.append([message.texte, None])
            elif message.role == "cowork" and message.details and taches:
                evenement = json.loads(message.details)
                if evenement["type"] in PAUSES:
                    taches[-1][1] = evenement
        lignes = []
        for demande, fin in taches[:-1][-TACHES_RESUMEES:]:  # la dernière est la demande en cours
            court = " ".join(demande.split())
            court = court if len(court) <= 200 else court[:199] + "…"
            lignes.append(f'- "{court}" → {_derniere_tache(fin) if fin else "no result"}')
        return "\n".join(lignes)

    # ---- suivre, décider, arrêter -----------------------------------------

    def en_cours(self, conversation_id: str) -> bool:
        session = self._sessions.get(conversation_id)
        return session is not None and not session.fini

    def flux(self, conversation_id: str, depuis: int = 0) -> Iterator[str]:
        """Les évènements de la tâche (à partir du n° `depuis`), puis le direct jusqu'à la fin."""
        session = self._sessions.get(conversation_id)
        if session is None:
            return
        position = max(0, depuis)
        while True:
            with session.condition:
                session.condition.wait_for(lambda: position < len(session.evenements) or session.fini, timeout=15)
                nouveaux = session.evenements[position:]
                fini = session.fini
            if not nouveaux and not fini:
                yield ": ping\n\n"  # garde la connexion ; révèle un navigateur parti
                continue
            for evenement in nouveaux:
                yield f"data: {json.dumps(evenement, ensure_ascii=False)}\n\n"
            position += len(nouveaux)
            if fini:
                return

    def instantane(self, conversation_id: str, lire: Callable[[], T]) -> tuple[T, dict]:
        """`lire()` (les messages enregistrés) et l'état de la tâche, pris ensemble : les
        évènements n° < depuis sont dans ce qu'a lu `lire`, les suivants viendront du flux."""
        session = self._sessions.get(conversation_id)
        if session is None:
            return lire(), {"en_cours": False, "depuis": 0}
        with session.condition:
            return lire(), {"en_cours": not session.fini, "depuis": len(session.evenements)}

    def etat(self, conversation_id: str) -> dict:
        """Statut, plan, évènements, résumé et bilan de la dernière tâche (relus dans
        l'historique si elle n'est plus en mémoire)."""
        session = self._sessions.get(conversation_id)
        if session is not None:
            with session.condition:
                evenements, statut = list(session.evenements), session.statut
        else:
            evenements = self._derniere_tache_enregistree(conversation_id)
            fin = next((e for e in reversed(evenements) if e["type"] in PAUSES), None)
            statut = STATUT_APRES[fin["type"]] if fin else "idle"
        plan = next((e["etapes"] for e in reversed(evenements) if e["type"] == "plan"), [])
        fin = next((e for e in reversed(evenements) if e["type"] in PAUSES), {})
        return {
            "statut": statut,
            "plan": plan,
            "evenements": evenements,
            "resume": fin.get("resume"),
            "question": fin.get("question"),
            "bilan": fin.get("bilan"),
        }

    def decider(self, conversation_id: str, etape: int, reponse: str, toujours: bool) -> bool:
        """Répond à la demande d'accord n° `etape`. False s'il n'y en a pas d'ouverte sous ce
        numéro : une réponse en retard ne doit pas valoir pour une autre action dangereuse."""
        session = self._sessions.get(conversation_id)
        if session is None or session.fini:
            return False
        with session.condition:
            if session.etape_en_attente is None or etape != session.etape_en_attente:
                return False
            session.etape_en_attente = None
            session.reponse_accord = reponse == "continuer"
            if toujours and session.reponse_accord:
                self._toujours.setdefault(conversation_id, set()).add(session.action_en_attente)
            session.accord.set()
        return True

    def etats_en_cours(self) -> list[dict]:
        """Le statut de chaque tâche non finie : le flux global de l'app commence par là
        (une demande d'accord déjà en attente doit se voir dès l'ouverture)."""
        etats = []
        for conversation_id, session in list(self._sessions.items()):
            with session.condition:
                if not session.fini:
                    etats.append({"conversation_id": conversation_id, "type": "statut", "statut": session.statut,
                                  "etape": len(session.evenements)})
        return etats

    def arreter(self, conversation_id: str) -> None:
        session = self._sessions.get(conversation_id)
        if session is None:
            return
        session.arret.set()
        session.accord.set()  # débloque un accord en attente

    # ---- processus --------------------------------------------------------

    def processus(self, conversation_id: str) -> list[dict]:
        gestionnaire = self._processus.get(conversation_id)
        return gestionnaire.liste() if gestionnaire else []

    def arreter_processus(self, conversation_id: str, numero: str) -> Resultat:
        gestionnaire = self._processus.get(conversation_id)
        if gestionnaire is None:
            return Resultat(False, f"no process #{numero}")
        return gestionnaire.arreter(numero)

    def oublier(self, conversation_id: str) -> None:
        """La conversation est supprimée : sa tâche et ses processus s'arrêtent (plus rien ne
        les montre dans l'app), ses autorisations « toujours » sont oubliées."""
        self.arreter(conversation_id)
        with self._verrou:
            gestionnaire = self._processus.pop(conversation_id, None)
            self._toujours.pop(conversation_id, None)
        if gestionnaire is not None:
            gestionnaire.arreter_tout()

    def arreter_tout(self) -> None:
        """Agent First s'arrête : les tâches d'abord (sinon l'une d'elles pourrait encore
        lancer un serveur qui survivrait), puis les processus."""
        for conversation_id, session in list(self._sessions.items()):
            if not session.fini:
                session.raison_arret = session.raison_arret or "Agent First s'est arrêté"
                self.arreter(conversation_id)
        for gestionnaire in list(self._processus.values()):
            gestionnaire.arreter_tout()

    def _processus_de(self, conversation_id: str, dossier: Path) -> GestionnaireProcessus:
        with self._verrou:
            gestionnaire = self._processus.get(conversation_id)
            if gestionnaire is None:
                gestionnaire = self._fabrique_processus(
                    dossier, lambda liste: self._processus_change(conversation_id, liste)
                )
                self._processus[conversation_id] = gestionnaire
            return gestionnaire

    def _processus_change(self, conversation_id: str, liste: list[dict]) -> None:
        session = self._sessions.get(conversation_id)
        if session is not None and not session.fini:
            self._emettre(conversation_id, session, {"type": "processus", "liste": liste})
        elif self._diffuseur is not None:  # tâche finie : seule l'app (en-tête) est concernée
            self._diffuseur.publier({"conversation_id": conversation_id, "type": "processus", "liste": liste})

    # ---- interne ----------------------------------------------------------

    def _demander(self, conversation_id: str, session: _Session, action: Action) -> bool:
        if action.nom in self._toujours.get(conversation_id, set()):
            return True
        # L'accord a été préparé (effacé, étape notée) à l'émission de « demande » : une réponse
        # arrivée entre-temps n'est pas perdue.
        if not session.accord.wait(self._delai_accord):
            session.raison_arret = f"pas de réponse à la demande d'accord en {self._delai_accord / 60:.0f} min"
            session.arret.set()
        session.etape_en_attente = None
        if session.arret.is_set():
            return False
        return session.reponse_accord

    @staticmethod
    def _finir(session: _Session) -> None:
        with session.condition:
            session.fini = True
            session.condition.notify_all()

    def _emettre(self, conversation_id: str, session: _Session, evenement: dict) -> None:
        if evenement["type"] == "demande" and evenement.get("action") in self._toujours.get(conversation_id, set()):
            # Déjà autorisée « toujours » : pas de carte d'accord, mais l'action reste visible.
            evenement = {**evenement, "type": "autorise"}
        type_ = evenement["type"]
        if type_ in PAUSES:
            evenement = {**evenement, "bilan": session.tache.bilan(self.processus(conversation_id))}
        with session.condition:
            evenement = {**evenement, "etape": len(session.evenements)}
            if type_ == "demande":  # préparé avant d'être visible : une réponse immédiate compte
                session.accord.clear()
                session.action_en_attente = evenement.get("action", "")
                session.etape_en_attente = evenement["etape"]
            if type_ not in NON_ENREGISTRES:
                try:
                    self._historique.ajouter_etape(conversation_id, evenement)
                except Exception:
                    journal.exception("Étape Cowork non enregistrée")
            session.evenements.append(evenement)
            nouveau_statut = evenement["statut"] if type_ == "statut" else STATUT_APRES.get(type_)
            if nouveau_statut is None and type_ not in NON_ENREGISTRES:
                nouveau_statut = "running"
            change = nouveau_statut is not None and nouveau_statut != session.statut
            if change:
                session.statut = nouveau_statut
                if type_ != "statut":
                    session.evenements.append({"type": "statut", "statut": nouveau_statut, "etape": len(session.evenements)})
            session.condition.notify_all()
            statut = session.statut
        if self._diffuseur is not None:
            publie = {"conversation_id": conversation_id, "type": type_, "etape": evenement["etape"], "statut": statut}
            if "liste" in evenement:  # processus : l'en-tête de l'app a besoin de la liste
                publie["liste"] = evenement["liste"]
            self._diffuseur.publier(publie)

    def _derniere_tache_enregistree(self, conversation_id: str) -> list[dict]:
        """Les étapes enregistrées depuis le dernier message de l'utilisateur."""
        try:
            messages = self._historique.messages(conversation_id)
        except KeyError:
            return []
        etapes: list[dict] = []
        for message in messages:
            if message.role == "toi":
                etapes = []
            elif message.role == "cowork" and message.details:
                etapes.append(json.loads(message.details))
        return etapes

    def _ranger(self) -> None:
        """Ne garde en mémoire que les dernières tâches finies (appelé sous self._verrou)."""
        finies = [cle for cle, s in self._sessions.items() if s.fini]
        for cle in finies[: max(0, len(finies) - SESSIONS_GARDEES)]:
            del self._sessions[cle]


def _processus_actifs(liste: list[dict]) -> str:
    actifs = [p for p in liste if p["actif"]]
    return "; ".join(
        f"#{p['id']} {p['commande']} (since {datetime.fromisoformat(p['depuis']):%H:%M})" for p in actifs
    )


def _derniere_tache(fin: dict | None) -> str:
    """La ligne LAST TASK du cadre : comment la tâche précédente a fini et ce qu'elle a changé."""
    if fin is None:
        return ""
    morceaux = [LIBELLE_FIN.get(fin["type"], fin["type"])]
    if fin.get("resume"):
        morceaux.append(f"summary: {fin['resume']}")
    elif fin.get("question"):
        morceaux.append(f"question: {fin['question']}")
    elif fin.get("corps"):
        morceaux.append(f"reason: {fin['corps']}")
    bilan = fin.get("bilan") or {}
    for cle, libelle in (("crees", "created"), ("modifies", "modified"), ("supprimes", "deleted")):
        if bilan.get(cle):
            morceaux.append(f"{libelle}: {', '.join(bilan[cle])}")
    if bilan.get("plan_inacheve"):
        morceaux.append(f"unchecked plan steps: {'; '.join(bilan['plan_inacheve'])}")
    return " — ".join(morceaux)
