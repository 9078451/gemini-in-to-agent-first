"""Les assistants qu'Agent First pilote (Gemini, ChatGPT, Claude…) : pour chacun, son
profil de site, ses files d'attente (une par onglet) et la liste de ses modèles."""
from dataclasses import dataclass

from agent_first.cache_modes import CacheModes
from agent_first.file_attente import FileAttente
from pilote.sites import Site


@dataclass
class Fournisseur:
    site: Site
    file_chat: FileAttente  # le Chat de l'app et l'API réseau
    file_cowork: FileAttente  # les tâches Cowork (Gemini : un onglet à part ; les autres : le même)
    modes: CacheModes

    @property
    def nom(self) -> str:
        return self.site.nom

    @property
    def libelle(self) -> str:
        return self.site.libelle

    @property
    def outils(self) -> tuple[str, ...]:
        return self.site.outils

    def decrire(self) -> dict:
        lus = self.modes.lire()
        return {
            "nom": self.nom, "libelle": self.libelle, "outils": list(self.outils), "ouvert": self.file_chat.pilote_pret(),
            "modeles": [vars(o) for o in lus.modeles], "niveaux": [vars(o) for o in lus.niveaux],
        }
