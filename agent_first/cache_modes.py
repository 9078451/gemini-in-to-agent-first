"""Les modèles et niveaux de réflexion proposés par Gemini, lus une fois puis gardés.

Partagé par l'app et l'API réseau, lu dans l'onglet du Chat : une tâche Cowork (dans
son propre onglet) ne l'empêche pas. Tant que Chrome est fermé, que l'onglet du Chat
est occupé ou que la lecture échoue, la liste par défaut (`config`) sert.
"""
import logging

from agent_first.file_attente import FileAttente
from pilote.modeles import Modes

journal = logging.getLogger(__name__)


class CacheModes:
    def __init__(self, file_chat: FileAttente, chrome_lance, par_defaut: Modes, paresseux: bool = False) -> None:
        self._file = file_chat
        self._chrome_lance = chrome_lance
        self._par_defaut = par_defaut
        self._modes: Modes | None = None
        # Un site dont la fenêtre n'a pas encore servi : lire ses modèles l'ouvrirait. On attend
        # son premier message ; la liste par défaut sert jusque-là.
        self._paresseux = paresseux

    def lire(self) -> Modes:
        # Onglet du Chat occupé (une longue réponse) : on n'attend pas son tour,
        # la liste par défaut sert et la vraie sera lue quand il sera libre.
        ouvert = not self._paresseux or self._file.pilote_pret()
        if self._modes is None and ouvert and self._chrome_lance() and not self._file.occupee():
            futur = self._file.soumettre(lambda pilote: pilote.lister_modes())
            try:
                lus = futur.result(timeout=30)
                if lus.modeles:
                    self._modes = lus
            except Exception:
                futur.cancel()  # pas encore commencée : qu'elle ne passe pas après coup
                journal.warning("Modèles illisibles dans Gemini : liste par défaut", exc_info=True)
        return self._modes or self._par_defaut

    def oublier(self) -> None:
        """La liste a changé (choix introuvable ou bloqué) : relue à la prochaine demande."""
        self._modes = None
