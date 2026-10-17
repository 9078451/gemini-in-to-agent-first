"""Les médias créés par Gemini (images, vidéos, sons), gardés sur le PC.

Un dossier par conversation (`donnees/medias/<conversation>/`) : retirer la conversation
de l'historique retire aussi ses médias. Un média est désigné par « <conversation>/<fichier> »,
son identifiant dans l'historique, l'app et l'API réseau.
"""
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Iterable

from pilote.medias import EXTENSIONS, extension
from pilote.modeles import Media

journal = logging.getLogger(__name__)

FORME_CONVERSATION = re.compile(r"[0-9a-f]{32}")
FORME_FICHIER = re.compile(r"[0-9a-f]{12}\.[a-z0-9]{2,5}")
MIMES = {ext: mime for mime, ext in EXTENSIONS.items()}


class Mediatheque:
    def __init__(self, dossier: Path) -> None:
        self._dossier = dossier

    def enregistrer(self, conversation_id: str, medias: Iterable[Media]) -> list[dict]:
        """Écrit les médias sur le disque ; renvoie leur description pour l'historique."""
        if not FORME_CONVERSATION.fullmatch(conversation_id):
            raise ValueError(f"identifiant de conversation invalide : {conversation_id}")
        decrits = []
        for media in medias:
            dossier = self._dossier / conversation_id
            dossier.mkdir(parents=True, exist_ok=True)
            fichier = f"{uuid.uuid4().hex[:12]}.{extension(media.mime)}"
            provisoire = dossier / f"{fichier}.part"
            provisoire.write_bytes(media.donnees)
            os.replace(provisoire, dossier / fichier)  # jamais de fichier à moitié écrit
            decrits.append({
                "id": f"{conversation_id}/{fichier}",
                "type": media.type,
                "mime": media.mime,
                "octets": len(media.donnees),
                "description": media.description,
            })
        return decrits

    def chemin(self, identifiant: str) -> Path | None:
        """Le fichier du média « <conversation>/<fichier> », ou None (inconnu ou mal formé)."""
        conversation_id, _, fichier = identifiant.partition("/")
        if not (FORME_CONVERSATION.fullmatch(conversation_id) and FORME_FICHIER.fullmatch(fichier)):
            return None
        chemin = self._dossier / conversation_id / fichier
        return chemin if chemin.is_file() else None

    def supprimer(self, conversation_id: str) -> None:
        if FORME_CONVERSATION.fullmatch(conversation_id):
            shutil.rmtree(self._dossier / conversation_id, ignore_errors=True)


def mime_de(chemin: Path) -> str:
    return MIMES.get(chemin.suffix.lstrip("."), "application/octet-stream")
