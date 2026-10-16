"""L'action « visit » : une requête HTTP vers un serveur local, pour que Gemini
vérifie lui-même ce qu'il a lancé.

Seulement localhost, et jamais les ports d'Agent First ni celui du Chrome dédié :
sinon Gemini pourrait valider lui-même une demande d'accord, ou piloter le Chrome
connecté au compte Google de l'utilisateur.
"""
import http.client
import json
import time
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
    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SansRedirection())  # jamais via un proxy
    fin = time.monotonic() + delai
    try:
        with ouvreur.open(requete, timeout=delai) as reponse:
            brut, complet = _lire_borne(reponse, taille_max * 4, fin)
            return _resultat(reponse.status, reponse.headers, brut, complet, True, taille_max)
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:  # une redirection n'est pas suivie : elle pourrait viser un port interdit
            cible = e.headers.get("Location", "?")
            return Resultat(True, f"HTTP {e.code} redirect\nLocation: {cible} (redirects are not followed: visit it yourself if it is local)")
        brut, complet = _lire_borne(e, taille_max * 4, fin)
        return _resultat(e.code, e.headers, brut, complet, False, taille_max)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:  # HTTPException : réponse qui n'est pas du HTTP
        return Resultat(False, f"connection failed: {getattr(e, 'reason', e)}")


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _lire_borne(reponse, limite: int, fin: float) -> tuple[bytes, bool]:
    """Lit au plus `limite` octets avant l'heure `fin` : un flux sans fin (SSE…) ou un
    très gros corps ne doit pas bloquer la tâche. Renvoie (octets, lu en entier ?)."""
    morceaux, total = [], 0
    while total < limite:
        reste = fin - time.monotonic()
        if reste <= 0:
            return b"".join(morceaux), False
        _regler_attente(reponse, reste)
        try:
            morceau = reponse.read1(min(65536, limite - total))
        except (TimeoutError, OSError):
            return b"".join(morceaux), False
        if not morceau:
            return b"".join(morceaux), True
        morceaux.append(morceau)
        total += len(morceau)
    return b"".join(morceaux), False


def _regler_attente(reponse, secondes: float) -> None:
    """Chaque lecture attend au plus le temps restant (sinon : le délai d'ouverture, à chaque fois)."""
    try:
        reponse.fp.raw._sock.settimeout(max(0.05, secondes))
    except AttributeError:
        pass  # objet sans socket accessible : le délai d'ouverture s'applique


def _est_json(texte: str) -> bool:
    try:
        json.loads(texte)
        return True
    except ValueError:
        return False


def _resultat(code: int, entetes, brut: bytes, complet: bool, ok: bool, taille_max: int) -> Resultat:
    texte = brut.decode(entetes.get_content_charset() or "utf-8", errors="replace")
    if len(texte) > taille_max:
        texte = texte[:taille_max] + "\n…(cut)"
    elif not complet:
        texte += "\n…(stopped reading: the response did not end in time)"
    annonce = entetes.get("Content-Length")
    taille = f"{annonce} bytes" if annonce else f"{len(brut)}{'' if complet else '+'} bytes"
    return Resultat(ok, f"HTTP {code} {entetes.get_content_type()} {taille}\n{texte}")
