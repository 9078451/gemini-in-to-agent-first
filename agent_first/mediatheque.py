"""Les médias créés par Gemini (images, vidéos, sons) et les fichiers joints aux messages,
gardés sur le PC.

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
FORME_FICHIER = re.compile(r"[0-9a-f]{12}\.[a-z0-9]{1,5}")
# Servis tels quels ; tout autre fichier (HTML, SVG, script…) part en téléchargement.
MIMES = {ext: mime for mime, ext in EXTENSIONS.items()} | {
    "pdf": "application/pdf", "txt": "text/plain; charset=utf-8", "md": "text/plain; charset=utf-8",
    "csv": "text/plain; charset=utf-8", "json": "text/plain; charset=utf-8",
}
TYPES_PIECES = ("image", "video", "audio")


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
            fichier = f"{uuid.uuid4().hex[:12]}.{_extension(media)}"
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


def type_de(mime: str) -> str:
    """« image », « video », « audio », ou « fichier » (PDF, texte…) d'après le type MIME."""
    famille = mime.split("/")[0].lower()
    return famille if famille in TYPES_PIECES else "fichier"


def _extension(media: Media) -> str:
    """Celle du nom d'origine d'un fichier joint (« rapport.pdf »), sinon d'après son type."""
    trouve = re.search(r"\.([A-Za-z0-9]{1,5})$", media.description or "")
    if media.type == "fichier" and trouve:
        return trouve.group(1).lower()
    return extension(media.mime)
