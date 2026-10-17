"""Les processus en arrière-plan d'une conversation Cowork (`start`, `logs`, `stop`).

Une commande `run` doit se terminer ; un serveur, lui, tourne. `start` le lance
sans l'attendre, lit ce qu'il écrit pendant quelques secondes et répond à Gemini,
qui peut ensuite le visiter, lire sa sortie ou l'arrêter. Les processus survivent à
la tâche (le serveur reste utilisable) et sont tous arrêtés avec Agent First.
"""
import logging
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from cowork.actions import commande_powershell, tuer_arbre
from cowork.catalogue import Resultat
from cowork.job_windows import rattacher

journal = logging.getLogger(__name__)
_GARDE = 4  # on garde au plus taille_max × _GARDE caractères de sortie par processus


class _Processus:
    def __init__(self, numero: int, commande: str, popen: subprocess.Popen, taille_max: int) -> None:
        self.numero = numero
        self.commande = commande
        self.popen = popen
        self.depuis = datetime.now().isoformat(timespec="seconds")
        self.fini = threading.Event()
        self._taille_max = taille_max
        self._sortie = ""
        self._lu = 0  # caractères déjà renvoyés à Gemini
        self._verrou = threading.Lock()

    @property
    def actif(self) -> bool:
        return self.popen.poll() is None

    def ajouter(self, texte: str) -> None:
        with self._verrou:
            self._sortie += texte
            exces = len(self._sortie) - self._taille_max * _GARDE
            if exces > 0:
                self._sortie = self._sortie[exces:]
                self._lu = max(0, self._lu - exces)

    def nouveau(self) -> str:
        """La sortie produite depuis la dernière lecture (coupée à taille_max, la fin gardée)."""
        with self._verrou:
            texte, self._lu = self._sortie[self._lu :], len(self._sortie)
        if len(texte) > self._taille_max:
            texte = "(cut)…\n" + texte[-self._taille_max :]
        return texte.strip()

    def vers_dict(self) -> dict:
        return {
            "id": self.numero,
            "commande": self.commande,
            "depuis": self.depuis,
            "actif": self.actif,
            "code": self.popen.returncode,
        }


class GestionnaireProcessus:
    def __init__(
        self,
        dossier: Path,
        max_processus: int,
        attente_demarrage: float,
        taille_max: int,
        commande: Callable[[str], list[str]] = commande_powershell,
        au_changement: Callable[[list[dict]], None] = lambda liste: None,
    ) -> None:
        self._dossier = dossier
        self._max = max_processus
        self._attente = attente_demarrage
        self._taille_max = taille_max
        self._commande = commande
        self._au_changement = au_changement
        self._processus: list[_Processus] = []
        self._verrou = threading.Lock()

    def demarrer(self, commande: str) -> Resultat:
        with self._verrou:
            actifs = [p for p in self._processus if p.actif]
            if len(actifs) >= self._max:
                liste = ", ".join(f"#{p.numero} {p.commande}" for p in actifs)
                return Resultat(False, f"{len(actifs)} processes already running ({liste}): stop one first")
            popen = subprocess.Popen(
                self._commande(commande),
                cwd=self._dossier,
                # PYTHONUNBUFFERED : sans lui, les print() d'un serveur Python restent en mémoire (sortie en tube)
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            rattacher(popen.pid)  # meurt avec Agent First, même s'il plante
            processus = _Processus(len(self._processus) + 1, commande, popen, self._taille_max)
            self._processus.append(processus)
        threading.Thread(target=self._lire, args=(processus,), name=f"processus-{processus.numero}", daemon=True).start()
        self._signaler()
        processus.fini.wait(self._attente)  # rend la main plus tôt s'il s'arrête tout de suite
        sortie = processus.nouveau()
        if processus.fini.is_set():
            code = popen.returncode
            corps = f"#{processus.numero} ended right away (exit code {code})\n{sortie or '(no output)'}"
            return Resultat(code == 0, corps, code=code)
        return Resultat(True, f"started #{processus.numero} (pid {popen.pid})\n{sortie or '(no output yet)'}")

    def sortie(self, numero: str) -> Resultat:
        processus = self._trouver(numero)
        if processus is None:
            return self._inconnu(numero)
        texte = processus.nouveau() or "(no new output)"
        if not processus.actif:
            texte += f"\n#{processus.numero} has ended (exit code {processus.popen.returncode})"
        return Resultat(True, texte)

    def arreter(self, numero: str) -> Resultat:
        processus = self._trouver(numero)
        if processus is None:
            return self._inconnu(numero)
        if not processus.actif:
            return Resultat(True, f"#{processus.numero} had already ended (exit code {processus.popen.returncode})")
        self._tuer(processus)
        fin = processus.nouveau()
        self._signaler()
        return Resultat(True, f"stopped #{processus.numero}" + (f"\nlast output:\n{fin}" if fin else ""))

    def arreter_tout(self) -> None:
        with self._verrou:
            actifs = [p for p in self._processus if p.actif]
        for processus in actifs:
            self._tuer(processus)
        if actifs:
            self._signaler()

    def liste(self) -> list[dict]:
        with self._verrou:
            return [p.vers_dict() for p in self._processus]

    # ---- interne --------------------------------------------------------

    def _lire(self, processus: _Processus) -> None:
        for ligne in processus.popen.stdout:
            processus.ajouter(ligne)
        processus.popen.wait()
        processus.fini.set()
        self._signaler()

    def _tuer(self, processus: _Processus) -> None:
        tuer_arbre(processus.popen.pid)
        try:
            processus.popen.wait(5)
        except subprocess.TimeoutExpired:
            processus.popen.kill()
        processus.fini.wait(2)  # laisse le lecteur ramasser la fin de la sortie

    def _trouver(self, numero: str) -> _Processus | None:
        try:
            n = int(str(numero).strip().lstrip("#"))
        except ValueError:
            return None
        with self._verrou:
            return next((p for p in self._processus if p.numero == n), None)

    def _inconnu(self, numero: str) -> Resultat:
        connus = ", ".join(f"#{p['id']}" for p in self.liste()) or "none"
        return Resultat(False, f"no process #{str(numero).lstrip('#')} (known: {connus})")

    def _signaler(self) -> None:
        try:
            self._au_changement(self.liste())
        except Exception:  # l'affichage ne doit jamais casser un processus
            journal.exception("Changement de processus non signalé")
