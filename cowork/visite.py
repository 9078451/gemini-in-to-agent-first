"""L'action « visit » : une requête HTTP vers un serveur local, pour que Gemini
vérifie lui-même ce qu'il a lancé.

Seulement localhost, et jamais les ports d'Agent First ni celui du Chrome dédié :
sinon Gemini pourrait valider lui-même une demande d'accord, ou piloter le Chrome
connecté au compte Google de l'utilisateur.
"""
import http.client
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from cowork.catalogue import Resultat

HOTES_LOCAUX = {"localhost", "127.0.0.1", "::1"}


def visiter(
    url: str, methode: str, corps: str | None, ports_interdits: frozenset[int], delai: float, taille_max: int
) -> Resultat:
    try:
        morceaux = urlsplit(url)
        port = morceaux.port or (443 if morceaux.scheme == "https" else 80)
    except ValueError:
        return Resultat(False, f"invalid url: {url}")
    if morceaux.scheme not in ("http", "https") or (morceaux.hostname or "").lower() not in HOTES_LOCAUX:
        return Resultat(False, "only localhost addresses can be visited (http://localhost:PORT/…)")
    if port in ports_interdits:
        return Resultat(False, f"port {port} is not allowed: it belongs to Agent First or its Chrome")
    donnees = corps.encode("utf-8") if corps else None
    requete = urllib.request.Request(url, data=donnees, method=(methode or "GET").upper())
    if donnees:
        requete.add_header("Content-Type", "application/json" if _est_json(corps) else "text/plain; charset=utf-8")
    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # localhost : jamais via un proxy
    try:
        with ouvreur.open(requete, timeout=delai) as reponse:
            return _resultat(reponse.status, reponse.headers, reponse.read(), True, taille_max)
    except urllib.error.HTTPError as e:
        return _resultat(e.code, e.headers, e.read(), False, taille_max)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:  # HTTPException : réponse qui n'est pas du HTTP
        return Resultat(False, f"connection failed: {getattr(e, 'reason', e)}")


def _est_json(texte: str) -> bool:
    try:
        json.loads(texte)
        return True
    except ValueError:
        return False


def _resultat(code: int, entetes, brut: bytes, ok: bool, taille_max: int) -> Resultat:
    texte = brut.decode(entetes.get_content_charset() or "utf-8", errors="replace")
    if len(texte) > taille_max:
        texte = texte[:taille_max] + "\n…(cut)"
    return Resultat(ok, f"HTTP {code} {entetes.get_content_type()} {len(brut)} bytes\n{texte}")
