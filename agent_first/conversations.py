"""Mémoire : identifiant de conversation local -> adresse de la conversation Gemini."""
import json
import logging
import os
import threading
import uuid
from pathlib import Path

journal = logging.getLogger(__name__)


class ConversationInconnue(KeyError):
    pass


class MemoireConversations:
    def __init__(self, fichier: Path) -> None:
        self._fichier = fichier
        self._verrou = threading.Lock()
        self._adresses: dict[str, str | None] = self._charger()

    def creer(self) -> str:
        with self._verrou:
            identifiant = uuid.uuid4().hex
            self._adresses[identifiant] = None
            self._sauver()
            return identifiant

    def adresse(self, identifiant: str) -> str | None:
        with self._verrou:
            if identifiant not in self._adresses:
                raise ConversationInconnue(identifiant)
            return self._adresses[identifiant]

    def enregistrer(self, identifiant: str, adresse: str) -> None:
        with self._verrou:
            if identifiant not in self._adresses:
                raise ConversationInconnue(identifiant)
            self._adresses[identifiant] = adresse
            self._sauver()

    def _charger(self) -> dict[str, str | None]:
        if not self._fichier.exists():
            return {}
        try:
            donnees = json.loads(self._fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            donnees = None
        if not isinstance(donnees, dict):
            mis_de_cote = self._fichier.with_name(self._fichier.stem + ".corrompu.json")
            os.replace(self._fichier, mis_de_cote)
            journal.warning("%s illisible, mis de côté dans %s", self._fichier, mis_de_cote)
            return {}
        return donnees

    def _sauver(self) -> None:
        self._fichier.parent.mkdir(parents=True, exist_ok=True)
        temporaire = self._fichier.with_suffix(".tmp")
        temporaire.write_text(json.dumps(self._adresses, indent=2), encoding="utf-8")
        os.replace(temporaire, self._fichier)
