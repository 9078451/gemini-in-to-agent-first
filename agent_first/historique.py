"""Historique de l'app : conversations et messages, dans une base SQLite sur le PC."""
import json
import logging
import os
import sqlite3
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
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
    medias TEXT,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id);
"""
# Colonnes ajoutées après la v2 : migrées à l'ouverture des bases existantes.
COLONNES_AJOUTEES = {
    "conversations": [("mode", "TEXT NOT NULL DEFAULT 'chat'"), ("dossier", "TEXT"), ("source", "TEXT NOT NULL DEFAULT 'app'"),
                      ("tours_gemini", "INTEGER NOT NULL DEFAULT 0")],
    "messages": [("details", "TEXT"), ("medias", "TEXT")],
}
COLONNES_CONVERSATION = """c.id, c.titre, c.adresse, c.modele, c.niveau, c.mode, c.dossier, c.source, c.tours_gemini,
    c.cree_le, c.modifie_le,
    (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS nb_messages"""
COLONNES_MESSAGE = "id, conversation_id, role, texte, html, modele, niveau, duree, details, cree_le, medias"
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
    tours_gemini: int = 0  # messages envoyés dans la conversation Gemini en cours (Cowork)
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
    # Images, vidéos, sons de la réponse (voir `mediatheque`) : id, type, mime, octets, description.
    medias: list[dict] = field(default_factory=list)


def _message(ligne: sqlite3.Row) -> Message:
    valeurs = dict(ligne)
    valeurs["medias"] = json.loads(valeurs["medias"]) if valeurs.get("medias") else []
    return Message(**valeurs)


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
    ) -> Conversation:
        with self._verrou:
            identifiant, date = uuid.uuid4().hex, self._date()
            self._base.execute(
                """INSERT INTO conversations (id, modele, niveau, mode, dossier, source, cree_le, modifie_le)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifiant, modele, niveau, mode, dossier, source, date, date),
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
        return [_message(ligne) for ligne in lignes]

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
        medias: list[dict] | None = None,
    ) -> Message:
        with self._verrou:
            conversation = self._conversation(identifiant)
            date = self._date()
            curseur = self._base.execute(
                """INSERT INTO messages
                   (conversation_id, role, texte, html, modele, niveau, duree, details, medias, cree_le)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifiant, role, texte, html, modele, niveau, duree, details,
                 json.dumps(medias, ensure_ascii=False) if medias else None, date),
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
        return _message(ligne)

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

    def medias_recents(self, limite: int = 60, type_media: str | None = None) -> list[dict]:
        """Les derniers médias créés par Gemini (le plus récent d'abord), avec leur conversation."""
        trouves: list[dict] = []
        with self._verrou:
            lignes = self._base.execute(
                """SELECT m.medias, m.conversation_id, m.cree_le, c.titre FROM messages m
                   JOIN conversations c ON c.id = m.conversation_id
                   WHERE m.role = 'gemini' AND m.medias IS NOT NULL ORDER BY m.id DESC""",
            )
            for ligne in lignes:
                for media in reversed(json.loads(ligne["medias"])):
                    if type_media is None or media.get("type") == type_media:
                        trouves.append({**media, "conversation_id": ligne["conversation_id"],
                                        "titre": ligne["titre"], "cree_le": ligne["cree_le"]})
                if len(trouves) >= limite:
                    break
        return trouves[:limite]

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
                "SELECT modele, duree, medias FROM messages WHERE role = 'gemini' AND (? IS NULL OR cree_le >= ?)",
                (depuis, depuis),
            ).fetchall()
        modeles = Counter(r["modele"] for r in reponses if r["modele"])
        durees = [r["duree"] for r in reponses if r["duree"] is not None]
        return {
            "conversations": conversations,
            "messages": messages,
            "modele_favori": modeles.most_common(1)[0][0] if modeles else None,
            "temps_moyen": round(sum(durees) / len(durees), 1) if durees else None,
            "medias": sum(len(json.loads(r["medias"])) for r in reponses if r["medias"]),
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
