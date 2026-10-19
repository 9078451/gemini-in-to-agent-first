"""Historique de l'app : conversations et messages, dans une base SQLite sur le PC."""
import json
import logging
import os
import sqlite3
import threading
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

journal = logging.getLogger(__name__)

JOURS_PAR_PERIODE = {"7j": 7, "30j": 30, "tout": None}
LONGUEUR_TITRE = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    titre TEXT NOT NULL DEFAULT '',
    adresse TEXT,
    modele TEXT,
    niveau TEXT,
    mode TEXT NOT NULL DEFAULT 'chat',
    dossier TEXT,
    source TEXT NOT NULL DEFAULT 'app',
    tours_gemini INTEGER NOT NULL DEFAULT 0,
    fournisseur TEXT NOT NULL DEFAULT 'gemini',
    cree_le TEXT NOT NULL,
    modifie_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    texte TEXT NOT NULL,
    html TEXT,
    modele TEXT,
    niveau TEXT,
    duree REAL,
    details TEXT,
    fournisseur TEXT,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id);
"""
# Colonnes ajoutées après la v2 : migrées à l'ouverture des bases existantes.
COLONNES_AJOUTEES = {
    "conversations": [("mode", "TEXT NOT NULL DEFAULT 'chat'"), ("dossier", "TEXT"), ("source", "TEXT NOT NULL DEFAULT 'app'"),
                      ("tours_gemini", "INTEGER NOT NULL DEFAULT 0"), ("fournisseur", "TEXT NOT NULL DEFAULT 'gemini'")],
    "messages": [("details", "TEXT"), ("fournisseur", "TEXT")],
}
COLONNES_CONVERSATION = """c.id, c.titre, c.adresse, c.modele, c.niveau, c.mode, c.dossier, c.source, c.tours_gemini,
    c.fournisseur, c.cree_le, c.modifie_le,
    (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS nb_messages"""
COLONNES_MESSAGE = "id, conversation_id, role, texte, html, modele, niveau, duree, details, fournisseur, cree_le"
NON_VIDE = "EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)"


class ConversationInconnue(KeyError):
    pass


@dataclass(frozen=True)
class Conversation:
    id: str
    titre: str
    adresse: str | None
    modele: str | None
    niveau: str | None
    mode: str
    dossier: str | None
    cree_le: str
    modifie_le: str
    source: str = "app"  # « app » ou « api » (créée par un autre programme via l'API réseau)
    tours_gemini: int = 0  # messages envoyés dans la conversation en cours chez le fournisseur (Cowork)
    fournisseur: str = "gemini"  # celui de `adresse` : la conversation continue chez lui
    nb_messages: int = 0


@dataclass(frozen=True)
class Message:
    id: int
    conversation_id: str
    role: str
    texte: str
    html: str | None
    modele: str | None
    niveau: str | None
    duree: float | None
    details: str | None
    cree_le: str
    fournisseur: str | None = None  # celui qui a répondu (None : messages d'avant les fournisseurs)


def titre_depuis(texte: str) -> str:
    titre = " ".join(texte.split())
    return titre if len(titre) <= LONGUEUR_TITRE else titre[: LONGUEUR_TITRE - 1] + "…"


class Historique:
    def __init__(self, fichier: Path, maintenant: Callable[[], datetime] = datetime.now) -> None:
        self._fichier = fichier
        self._maintenant = maintenant
        self._verrou = threading.Lock()
        self._base = self._ouvrir()

    # ---- conversations --------------------------------------------------

    def creer(
        self,
        modele: str | None = None,
        niveau: str | None = None,
        mode: str = "chat",
        dossier: str | None = None,
        source: str = "app",
        fournisseur: str = "gemini",
    ) -> Conversation:
        with self._verrou:
            identifiant, date = uuid.uuid4().hex, self._date()
            self._base.execute(
                """INSERT INTO conversations (id, modele, niveau, mode, dossier, source, fournisseur, cree_le, modifie_le)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifiant, modele, niveau, mode, dossier, source, fournisseur, date, date),
            )
            self._base.commit()
            return self._conversation(identifiant)

    def conversation(self, identifiant: str) -> Conversation:
        with self._verrou:
            return self._conversation(identifiant)

    def lister(self, recherche: str = "", periode: str = "tout") -> list[Conversation]:
        motif, depuis = recherche.strip().lower(), self._depuis(periode)
        with self._verrou:
            lignes = self._base.execute(
                f"""SELECT {COLONNES_CONVERSATION} FROM conversations c
                    WHERE {NON_VIDE}
                      AND (? IS NULL OR c.modifie_le >= ?)
                      AND (? = '' OR instr(lower(c.titre), ?) > 0
                           OR EXISTS (SELECT 1 FROM messages m
                                      WHERE m.conversation_id = c.id AND instr(lower(m.texte), ?) > 0))
                    ORDER BY c.modifie_le DESC, c.rowid DESC""",
                (depuis, depuis, motif, motif, motif),
            ).fetchall()
        return [Conversation(**dict(ligne)) for ligne in lignes]

    def compter_tour(self, identifiant: str) -> None:
        """Un message de plus envoyé dans la conversation Gemini en cours."""
        with self._verrou:
            self._base.execute("UPDATE conversations SET tours_gemini = tours_gemini + 1 WHERE id = ?", (identifiant,))
            self._base.commit()

    def repartir(self, identifiant: str) -> None:
        """La prochaine demande part dans une conversation Gemini neuve."""
        with self._verrou:
            self._conversation(identifiant)
            self._base.execute("UPDATE conversations SET adresse = NULL, tours_gemini = 0 WHERE id = ?", (identifiant,))
            self._base.commit()

    def changer_fournisseur(self, identifiant: str, fournisseur: str, modele: str | None, niveau: str | None) -> None:
        """La conversation continue chez un autre fournisseur : l'ancienne adresse ne vaut plus."""
        with self._verrou:
            self._conversation(identifiant)
            self._base.execute(
                """UPDATE conversations SET fournisseur = ?, modele = ?, niveau = ?, adresse = NULL, tours_gemini = 0
                   WHERE id = ?""",
                (fournisseur, modele, niveau, identifiant),
            )
            self._base.commit()

    def regler_modele(self, identifiant: str, modele: str | None, niveau: str | None) -> None:
        """Autre modèle ou niveau chez le même fournisseur : la conversation continue."""
        with self._verrou:
            self._conversation(identifiant)
            self._base.execute("UPDATE conversations SET modele = ?, niveau = ? WHERE id = ?", (modele, niveau, identifiant))
            self._base.commit()

    def renommer(self, identifiant: str, titre: str) -> None:
        with self._verrou:
            self._conversation(identifiant)
            self._base.execute("UPDATE conversations SET titre = ? WHERE id = ?", (titre_depuis(titre), identifiant))
            self._base.commit()

    def enregistrer_adresse(self, identifiant: str, adresse: str) -> None:
        with self._verrou:
            self._conversation(identifiant)
            self._base.execute("UPDATE conversations SET adresse = ? WHERE id = ?", (adresse, identifiant))
            self._base.commit()

    def supprimer(self, identifiant: str) -> None:
        with self._verrou:
            self._conversation(identifiant)
            self._base.execute("DELETE FROM conversations WHERE id = ?", (identifiant,))
            self._base.commit()

    # ---- messages -------------------------------------------------------

    def messages(self, identifiant: str) -> list[Message]:
        with self._verrou:
            self._conversation(identifiant)
            lignes = self._base.execute(
                f"SELECT {COLONNES_MESSAGE} FROM messages WHERE conversation_id = ? ORDER BY id", (identifiant,)
            ).fetchall()
        return [Message(**dict(ligne)) for ligne in lignes]

    def ajouter_message(
        self,
        identifiant: str,
        role: str,
        texte: str,
        html: str | None = None,
        modele: str | None = None,
        niveau: str | None = None,
        duree: float | None = None,
        details: str | None = None,
        fournisseur: str | None = None,
    ) -> Message:
        with self._verrou:
            conversation = self._conversation(identifiant)
            date = self._date()
            curseur = self._base.execute(
                """INSERT INTO messages
                   (conversation_id, role, texte, html, modele, niveau, duree, details, fournisseur, cree_le)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifiant, role, texte, html, modele, niveau, duree, details, fournisseur, date),
            )
            titre = conversation.titre or (titre_depuis(texte) if role == "toi" else "")
            self._base.execute(
                """UPDATE conversations SET titre = ?, modifie_le = ?,
                   modele = coalesce(?, modele), niveau = coalesce(?, niveau) WHERE id = ?""",
                (titre, date, modele, niveau, identifiant),
            )
            self._base.commit()
            ligne = self._base.execute(
                f"SELECT {COLONNES_MESSAGE} FROM messages WHERE id = ?", (curseur.lastrowid,)
            ).fetchone()
        return Message(**dict(ligne))

    def ajouter_etape(self, identifiant: str, evenement: dict) -> Message:
        """Enregistre une étape Cowork : rôle « cowork », texte = type, détails en JSON."""
        return self.ajouter_message(
            identifiant,
            "cowork",
            evenement.get("type", ""),
            details=json.dumps(evenement, ensure_ascii=False),
        )

    def derniere_etape(self, identifiant: str, types: set[str]) -> dict | None:
        """La dernière étape Cowork de la conversation dont le type est dans `types`."""
        marques = ",".join("?" * len(types))
        with self._verrou:
            ligne = self._base.execute(
                f"""SELECT details FROM messages WHERE conversation_id = ? AND role = 'cowork'
                    AND texte IN ({marques}) ORDER BY id DESC LIMIT 1""",
                (identifiant, *sorted(types)),
            ).fetchone()
        return json.loads(ligne["details"]) if ligne and ligne["details"] else None

    # ---- statistiques ---------------------------------------------------

    def statistiques(self, periode: str = "7j") -> dict:
        depuis = self._depuis(periode)
        with self._verrou:
            conversations = self._base.execute(
                f"SELECT count(*) FROM conversations c WHERE {NON_VIDE} AND (? IS NULL OR c.modifie_le >= ?)",
                (depuis, depuis),
            ).fetchone()[0]
            messages = self._base.execute(
                "SELECT count(*) FROM messages WHERE role = 'toi' AND (? IS NULL OR cree_le >= ?)", (depuis, depuis)
            ).fetchone()[0]
            reponses = self._base.execute(
                "SELECT modele, duree FROM messages WHERE role = 'gemini' AND (? IS NULL OR cree_le >= ?)",
                (depuis, depuis),
            ).fetchall()
        modeles = Counter(r["modele"] for r in reponses if r["modele"])
        durees = [r["duree"] for r in reponses if r["duree"] is not None]
        return {
            "conversations": conversations,
            "messages": messages,
            "modele_favori": modeles.most_common(1)[0][0] if modeles else None,
            "temps_moyen": round(sum(durees) / len(durees), 1) if durees else None,
        }

    # ---- interne --------------------------------------------------------

    def _conversation(self, identifiant: str) -> Conversation:
        ligne = self._base.execute(
            f"SELECT {COLONNES_CONVERSATION} FROM conversations c WHERE c.id = ?", (identifiant,)
        ).fetchone()
        if ligne is None:
            raise ConversationInconnue(identifiant)
        return Conversation(**dict(ligne))

    def _date(self) -> str:
        return self._maintenant().isoformat(timespec="seconds")

    def _depuis(self, periode: str) -> str | None:
        jours = JOURS_PAR_PERIODE[periode]
        if jours is None:
            return None
        return (self._maintenant() - timedelta(days=jours)).isoformat(timespec="seconds")

    def _ouvrir(self) -> sqlite3.Connection:
        self._fichier.parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._connecter()
        except sqlite3.DatabaseError:
            mis_de_cote = self._fichier.with_name(self._fichier.stem + ".corrompu.db")
            os.replace(self._fichier, mis_de_cote)
            journal.warning("%s illisible, mis de côté dans %s", self._fichier, mis_de_cote)
            return self._connecter()

    def _connecter(self) -> sqlite3.Connection:
        base = sqlite3.connect(self._fichier, check_same_thread=False)
        try:
            base.row_factory = sqlite3.Row
            # WAL : une écriture (chaque étape Cowork) ne bloque plus les lectures et coûte bien moins.
            base.execute("PRAGMA journal_mode = WAL")
            base.execute("PRAGMA synchronous = NORMAL")
            base.execute("PRAGMA busy_timeout = 5000")
            base.execute("PRAGMA foreign_keys = ON")
            base.executescript(SCHEMA)
            self._migrer(base)
        except sqlite3.DatabaseError:
            base.close()
            raise
        return base

    def _migrer(self, base: sqlite3.Connection) -> None:
        """Ajoute les colonnes manquantes aux bases créées avant le mode Cowork."""
        for table, colonnes in COLONNES_AJOUTEES.items():
            presentes = {r["name"] for r in base.execute(f"PRAGMA table_info({table})")}
            for nom, definition in colonnes:
                if nom not in presentes:
                    base.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {definition}")
        base.commit()
