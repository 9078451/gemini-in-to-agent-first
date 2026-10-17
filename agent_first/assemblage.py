"""Assemble Agent First : files d'attente, service Cowork, app et API réseau.

Deux onglets Gemini, chacun sa file et son fil : les tâches Cowork dans l'un, le Chat
de l'app et l'API réseau dans l'autre. Une tâche Cowork (des minutes) ne fait plus
attendre le Chat. Séparé de `__main__` (journaux, Chrome, serveurs) pour être testé
avec de faux pilotes.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import FastAPI

import config
from agent_first.api_reseau import creer_api_reseau
from agent_first.cache_modes import CacheModes
from agent_first.cle_api import GardeCle
from agent_first.cowork_service import ServiceCowork
from agent_first.diffuseur import Diffuseur
from agent_first.file_attente import FileAttente, rechauffer
from agent_first.historique import Historique
from agent_first.mediatheque import Mediatheque
from agent_first.serveur import creer_app
from cowork.actions import Executeur
from cowork.boucle import Reglages
from cowork.processus import GestionnaireProcessus
from pilote.chrome import ONGLET_CHAT, ONGLET_COWORK
from pilote.modeles import Modes, Option, Pilote


@dataclass
class AgentFirst:
    file_cowork: FileAttente
    file_chat: FileAttente
    cowork: ServiceCowork
    app: FastAPI
    api: FastAPI | None
    garde: GardeCle | None

    def arreter(self) -> None:
        self.cowork.arreter_tout()  # les tâches, puis les serveurs qu'elles ont lancés
        self.file_cowork.arreter()
        self.file_chat.arreter()


def assembler(
    fabrique_pilote: Callable[[str], Pilote],
    chrome_lance: Callable[[], bool],
    historique: Historique,
    fichier_cle: Path | None,
    adresse_api: str | None = None,
    choisir_dossier: Callable[[], str | None] | None = None,
    dossier_medias: Path | None = None,
) -> AgentFirst:
    """`fabrique_pilote(role)` fabrique le pilote d'un onglet ; elle est appelée dans le fil
    de sa file. `fichier_cle` à None : pas d'API réseau. `dossier_medias` : où garder les
    images, vidéos et sons créés (par défaut, celui de `config`)."""
    mediatheque = Mediatheque(dossier_medias or config.DOSSIER_MEDIAS)
    medias = {"mediatheque": mediatheque, "delais_media": config.DELAI_MEDIA, "attente_file": config.ATTENTE_FILE}
    file_cowork = FileAttente(lambda: fabrique_pilote(ONGLET_COWORK), nom="file-gemini-cowork")
    file_chat = FileAttente(lambda: fabrique_pilote(ONGLET_CHAT), nom="file-gemini-chat")
    for file in (file_cowork, file_chat):
        file.demarrer()
        rechauffer(file)  # Chrome et les deux onglets Gemini prêts avant le premier message
    par_defaut = Modes(
        [Option(n, d, n == config.MODELE_ACTIF_PAR_DEFAUT) for n, d in config.MODELES_PAR_DEFAUT],
        [Option(n, d, n == config.NIVEAU_ACTIF_PAR_DEFAUT) for n, d in config.NIVEAUX_PAR_DEFAUT],
    )
    # Gemini ne doit pas pouvoir joindre Agent First (il validerait ses propres accords) ni le Chrome dédié.
    ports_interdits = frozenset({config.PORT_AGENT, config.PORT_API, config.PORT_CHROME})

    def fabrique_executeur(dossier, processus, arret):
        return Executeur(
            dossier, config.DELAI_COMMANDE, config.TAILLE_MAX_SORTIE, processus=processus,
            ports_interdits=ports_interdits, delai_visite=config.DELAI_VISITE, arret=arret,
        )

    def fabrique_processus(dossier, au_changement):
        return GestionnaireProcessus(
            dossier, config.MAX_PROCESSUS, config.ATTENTE_DEMARRAGE, config.TAILLE_MAX_SORTIE,
            au_changement=au_changement,
        )

    reglages = Reglages(
        max_tours=config.MAX_TOURS_COWORK, max_actions=config.MAX_ACTIONS_PAR_MESSAGE,
        echecs_max=config.ECHECS_FORMAT_MAX, taille_max=config.TAILLE_MAX_SORTIE,
        taille_max_message=config.TAILLE_MAX_MESSAGE, relances_fin_max=config.RELANCES_FIN_MAX,
    )
    diffuseur = Diffuseur()
    cache_modes = CacheModes(file_chat, chrome_lance, par_defaut)
    cowork = ServiceCowork(
        file_cowork, historique, fabrique_executeur, reglages, fabrique_processus,
        delai_accord=config.DELAI_ACCORD, delai_reponse=config.DELAI_REPONSE_COWORK,
        diffuseur=diffuseur, max_entrees=config.MAX_ENTREES_ARBORESCENCE, tours_max=config.TOURS_GEMINI_MAX,
    )
    garde, api = None, None
    if fichier_cle is not None:
        garde = GardeCle(fichier_cle, essais_max=config.ESSAIS_CLE_MAX)
        api = creer_api_reseau(
            file_chat, historique, cowork, garde, cache_modes, config.DELAI_AGENT,
            niveau_cowork=config.NIVEAU_ACTIF_PAR_DEFAUT, **medias,
        )
    app = creer_app(
        file_chat, historique, config.DELAI_AGENT, chrome_lance, par_defaut,
        config.DOSSIER_WEB, cowork=cowork, choisir_dossier=choisir_dossier,
        diffuseur=diffuseur, cache_modes=cache_modes, garde_api=garde, adresse_api=adresse_api,
        hotes_autorises=[config.HOTE_AGENT, "localhost"], **medias,
    )
    return AgentFirst(file_cowork, file_chat, cowork, app, api, garde)
