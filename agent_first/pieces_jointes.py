"""Les fichiers joints à un message (photos, PDF, sons…) : lus depuis l'app (base64) ou
l'API réseau (`data:`, adresse web), avant d'être confiés au pilote.

Partagé par le Chat de l'app et l'API réseau.
"""
import base64
import binascii
import re
import urllib.parse

import httpx

from agent_first.mediatheque import type_de
from pilote.modeles import Media

MAX_PIECES = 10
MAX_OCTETS = 50 * 1024 * 1024  # par fichier
DELAI_TELECHARGEMENT = 30.0  # s, pour une pièce donnée par son adresse web


class PieceIllisible(ValueError):
    """Le message de l'erreur est destiné à l'utilisateur."""


def depuis_base64(nom: str, mime: str, contenu: str) -> Media:
    try:
        donnees = base64.b64decode(contenu, validate=True)
    except (binascii.Error, ValueError):
        raise PieceIllisible(f"Pièce jointe « {nom} » illisible (base64 attendu).")
    return _piece(nom, mime, donnees)


def depuis_url(url: str, nom: str | None = None) -> Media:
    """Une pièce donnée par une adresse `data:` ou `http(s):` (format OpenAI)."""
    if url.startswith("data:"):
        entete, _, contenu = url.partition(",")
        mime = entete[5:].split(";")[0] or "application/octet-stream"
        nom = nom or f"piece.{_extension(mime)}"
        if ";base64" in entete:
            return depuis_base64(nom, mime, contenu)
        return _piece(nom, mime, urllib.parse.unquote_to_bytes(contenu))
    if not re.match(r"https?://", url, re.IGNORECASE):
        raise PieceIllisible("Pièce jointe : adresse data: ou http(s) attendue.")
    try:
        with httpx.stream("GET", url, timeout=DELAI_TELECHARGEMENT, follow_redirects=True) as reponse:
            reponse.raise_for_status()
            morceaux, taille = [], 0
            for morceau in reponse.iter_bytes():
                taille += len(morceau)
                if taille > MAX_OCTETS:
                    raise PieceIllisible(f"Pièce jointe trop lourde (plus de {MAX_OCTETS // 1_000_000} Mo) : {url}")
                morceaux.append(morceau)
            mime = reponse.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    except httpx.HTTPError as e:
        raise PieceIllisible(f"Pièce jointe impossible à télécharger ({url}) : {e}")
    nom = nom or urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1] or f"piece.{_extension(mime)}"
    return _piece(nom, mime, b"".join(morceaux))


def _piece(nom: str, mime: str, donnees: bytes) -> Media:
    if not donnees:
        raise PieceIllisible(f"Pièce jointe « {nom} » vide.")
    if len(donnees) > MAX_OCTETS:
        raise PieceIllisible(f"Pièce jointe « {nom} » trop lourde (plus de {MAX_OCTETS // 1_000_000} Mo).")
    nom = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", nom).strip() or "piece"
    mime = mime.strip().lower() or "application/octet-stream"
    return Media(type_de(mime), mime, donnees, nom[:120])


def _extension(mime: str) -> str:
    sous_type = mime.split("/")[-1].split("+")[0]
    return {"jpeg": "jpg", "plain": "txt", "mpeg": "mp3"}.get(sous_type, re.sub(r"[^a-z0-9]", "", sous_type)[:5] or "bin")
