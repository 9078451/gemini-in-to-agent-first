"""Ce qu'une API a dit dans chaque conversation.

Une API ne garde rien entre deux appels : chaque message repart avec tout l'échange.
Agent First le garde ici (`donnees/fils.db`), sous l'adresse de la conversation
(`api:<fournisseur>:<id>`), comme Gemini garde la sienne sous son URL.
"""
import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

SCHEMA = """CREATE TABLE IF NOT EXISTS fils (
    adresse TEXT PRIMARY KEY,
    messages TEXT NOT NULL,
    modifie_le TEXT NOT NULL
)"""


class MemoireFils:
    def __init__(self, fichier: Path) -> None:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        self._base = sqlite3.connect(fichier, check_same_thread=False)
        self._base.execute("PRAGMA journal_mode = WAL")
        self._base.execute("PRAGMA synchronous = NORMAL")
        self._base.execute(SCHEMA)
        self._verrou = threading.Lock()

    @staticmethod
    def nouvelle_adresse(fournisseur: str) -> str:
        return f"api:{fournisseur}:{uuid.uuid4().hex}"

    def lire(self, adresse: str | None) -> list[dict]:
        if not adresse:
            return []
        with self._verrou:
            ligne = self._base.execute("SELECT messages FROM fils WHERE adresse = ?", (adresse,)).fetchone()
        return json.loads(ligne[0]) if ligne else []

    def ecrire(self, adresse: str, messages: list[dict]) -> None:
        with self._verrou:
            self._base.execute(
                "INSERT OR REPLACE INTO fils (adresse, messages, modifie_le) VALUES (?, ?, ?)",
                (adresse, json.dumps(messages, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
            )
            self._base.commit()
