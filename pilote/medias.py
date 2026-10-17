"""Les médias d'une réponse de Gemini (images, vidéos, sons) : les repérer dans la page,
savoir s'ils sont encore en préparation, puis les télécharger.

Un média est téléchargé avec la session Google du Chrome dédié (ses cookies) : par son
adresse, en taille réelle si possible ; un `blob:` est lu dans la page ; en dernier
recours, une image est prise en capture d'écran.
"""
import base64
import logging
import re
import urllib.parse

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote.modeles import Media
from pilote.selecteurs import CONTENEUR_REPONSE, HORS_MEDIAS, MEDIA_EN_COURS

journal = logging.getLogger(__name__)

TAILLE_MIN_IMAGE = 64  # px : en dessous, une icône ou le logo d'une source, pas un média
MAX_MEDIAS = 8  # médias gardés par réponse
MAX_OCTETS = 300 * 1024 * 1024  # une vidéo Veo pèse quelques dizaines de Mo
DELAI_TELECHARGEMENT = 120.0  # s par essai
MARQUE = "data-agent-first-media"

_TROUVER = """
const visible = (e) => (e.checkVisibility ? e.checkVisibility() : !!e.offsetParent);
const source = (e) => e.currentSrc || e.src || (e.querySelector('source[src]') || {}).src || '';
const trouver = (element, s) => {
  const bloc = element.closest(s.conteneur) || element;
  const vus = new Set();
  const trouves = [];
  for (const e of bloc.querySelectorAll('img, video, audio')) {
    if (e.closest(s.hors)) continue;
    const url = source(e);
    if (!url || url.startsWith('data:image/svg') || vus.has(url)) continue;
    const type = e.tagName === 'IMG' ? 'image' : e.tagName === 'VIDEO' ? 'video' : 'audio';
    if (type === 'image') {
      const r = e.getBoundingClientRect();
      const largeur = r.width || e.naturalWidth, hauteur = r.height || e.naturalHeight;
      if (largeur < s.taille_min || hauteur < s.taille_min) continue;
    }
    vus.add(url);
    const description = (e.getAttribute('alt') || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim();
    trouves.push({element: e, type, url, description});
  }
  return {bloc, trouves};
};
"""

# Nombre de médias et s'il en reste un en préparation : lu pendant l'attente de la réponse.
ETAT_MEDIAS = "(element, s) => {" + _TROUVER + """
  const {bloc, trouves} = trouver(element, s);
  const en_attente = [...bloc.querySelectorAll(s.en_cours)].some(visible);
  return {nombre: trouves.length, en_attente};
}"""

# Les médias, chacun marqué dans la page (pour une capture d'écran de secours).
LISTER_MEDIAS = "(element, s) => {" + _TROUVER + """
  document.querySelectorAll('[' + s.marque + ']').forEach((e) => e.removeAttribute(s.marque));
  return trouver(element, s).trouves.slice(0, s.max).map((m, i) => {
    m.element.setAttribute(s.marque, String(i));
    return {type: m.type, url: m.url, description: m.description, repere: i};
  });
}"""

# Lit une adresse depuis la page (blob:, ou une adresse que la page a le droit de lire).
LIRE_DANS_LA_PAGE = """async (url) => {
  const r = await fetch(url, {credentials: 'include'});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const b = await r.blob();
  return await new Promise((ok, ko) => {
    const f = new FileReader();
    f.onload = () => ok(f.result);
    f.onerror = () => ko(f.error);
    f.readAsDataURL(b);
  });
}"""

EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp", "image/avif": "avif",
    "image/heic": "heic", "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm",
    "audio/mpeg": "mp3", "audio/aac": "aac", "audio/mp4": "m4a", "audio/wav": "wav", "audio/ogg": "ogg",
    "audio/flac": "flac", "audio/webm": "weba",
}
PAR_DEFAUT = {"image": "image/png", "video": "video/mp4", "audio": "audio/mpeg"}


class MediaIllisible(Exception):
    pass


def parametres() -> dict:
    return {"conteneur": CONTENEUR_REPONSE, "hors": HORS_MEDIAS, "en_cours": MEDIA_EN_COURS,
            "taille_min": TAILLE_MIN_IMAGE, "max": MAX_MEDIAS, "marque": MARQUE}


def etat_medias(reponse: Locator) -> tuple[int, bool]:
    """(nombre de médias, un média est-il encore en préparation) dans le bloc de la réponse."""
    try:
        etat = reponse.evaluate(ETAT_MEDIAS, parametres())
    except ErreurPlaywright:
        return 0, False  # la page se redessine : relu au tour suivant
    return int(etat["nombre"]), bool(etat["en_attente"])


def deviner_mime(donnees: bytes, annonce: str, type_media: str) -> str | None:
    """Le type du fichier d'après ses premiers octets (l'en-tête du serveur se trompe parfois),
    sinon celui annoncé. None si ce n'est pas un média (page de connexion, erreur…)."""
    debut = donnees[:16]
    mime = None
    if debut.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif debut.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif debut[:6] in (b"GIF87a", b"GIF89a"):
        mime = "image/gif"
    elif debut[:4] == b"RIFF" and debut[8:12] == b"WEBP":
        mime = "image/webp"
    elif debut[:4] == b"RIFF" and debut[8:12] == b"WAVE":
        mime = "audio/wav"
    elif debut[4:8] == b"ftyp":
        marque = debut[8:12]
        if marque in (b"avif", b"avis"):
            mime = "image/avif"
        elif marque in (b"heic", b"heix", b"mif1"):
            mime = "image/heic"
        elif marque.startswith(b"M4A") or type_media == "audio":
            mime = "audio/mp4"
        elif marque == b"qt  ":
            mime = "video/quicktime"
        else:
            mime = "video/mp4"
    elif debut.startswith(b"\x1a\x45\xdf\xa3"):
        mime = "audio/webm" if type_media == "audio" else "video/webm"
    elif debut.startswith(b"OggS"):
        mime = "audio/ogg"
    elif debut.startswith(b"fLaC"):
        mime = "audio/flac"
    elif debut.startswith(b"ID3"):
        mime = "audio/mpeg"
    elif len(debut) >= 2 and debut[0] == 0xFF and (debut[1] & 0xF6) == 0xF0:
        mime = "audio/aac"
    elif len(debut) >= 2 and debut[0] == 0xFF and (debut[1] & 0xE0) == 0xE0:
        mime = "audio/mpeg"
    if mime:
        return mime
    annonce = annonce.split(";")[0].strip().lower()
    if annonce.startswith(("image/", "video/", "audio/")) and "svg" not in annonce and donnees:
        return annonce
    return None


def extension(mime: str) -> str:
    return EXTENSIONS.get(mime) or re.sub(r"[^a-z0-9]", "", mime.split("/")[-1].split("+")[0].lower())[:5] or "bin"


def variantes(url: str, type_media: str) -> list[str]:
    """Les adresses à essayer, la meilleure d'abord : une image de googleusercontent.com est
    affichée réduite (« =s1024-rj ») ; « =s0 » demande la taille réelle."""
    hote = urllib.parse.urlsplit(url).hostname or ""
    if type_media == "image" and hote.endswith("googleusercontent.com") and "?" not in url:
        grande = re.sub(r"=[^/=]*$", "", url) + "=s0"
        if grande != url:
            return [grande, url]
    return [url]


def decoder_data_url(url: str) -> tuple[bytes, str]:
    entete, _, contenu = url.partition(",")
    mime = entete[5:].split(";")[0]
    if ";base64" in entete:
        return base64.b64decode(contenu), mime
    return urllib.parse.unquote_to_bytes(contenu), mime


def telecharger_medias(page: Page, reponse: Locator) -> tuple[list[Media], int]:
    """Les médias de la réponse, et le nombre de ceux qui n'ont pas pu être téléchargés."""
    try:
        trouves = reponse.evaluate(LISTER_MEDIAS, parametres())
    except ErreurPlaywright:
        journal.warning("Médias de la réponse illisibles", exc_info=True)
        return [], 0
    medias, perdus = [], 0
    for trouve in trouves:
        try:
            medias.append(_telecharger(page, trouve))
        except MediaIllisible as e:
            perdus += 1
            journal.warning("Média non récupéré (%s) : %s", trouve["url"][:120], e)
    return medias, perdus


def _telecharger(page: Page, trouve: dict) -> Media:
    type_media, url = trouve["type"], trouve["url"]
    essais = []
    if url.startswith("data:"):
        essais.append(lambda: decoder_data_url(url))
    elif url.startswith("blob:"):
        essais.append(lambda: _dans_la_page(page, url))
    else:
        essais += [lambda u=u: _par_requete(page, u) for u in variantes(url, type_media)]
        essais.append(lambda: _dans_la_page(page, url))
    if type_media == "image":
        essais.append(lambda: _capture(page, trouve["repere"]))
    raisons = []
    for essai in essais:
        try:
            donnees, annonce = essai()
        except (ErreurPlaywright, MediaIllisible, ValueError) as e:
            raisons.append(str(e).splitlines()[0][:120])
            continue
        if len(donnees) > MAX_OCTETS:
            raise MediaIllisible(f"trop lourd ({len(donnees) // 1_000_000} Mo)")
        mime = deviner_mime(donnees, annonce, type_media)
        if mime:
            return Media(type_media, mime, donnees, trouve.get("description", ""))
        raisons.append(f"contenu inattendu ({annonce or 'type inconnu'})")
    raise MediaIllisible(" ; ".join(raisons) or "aucun essai possible")


def _par_requete(page: Page, url: str) -> tuple[bytes, str]:
    """Avec les cookies du Chrome dédié : les fichiers créés par Gemini sont liés au compte."""
    reponse = page.context.request.get(
        url, headers={"Referer": "https://gemini.google.com/"}, timeout=DELAI_TELECHARGEMENT * 1000,
    )
    try:
        if not reponse.ok:
            raise MediaIllisible(f"HTTP {reponse.status}")
        taille = reponse.headers.get("content-length", "")
        if taille.isdigit() and int(taille) > MAX_OCTETS:
            raise MediaIllisible(f"trop lourd ({int(taille) // 1_000_000} Mo)")
        return reponse.body(), reponse.headers.get("content-type", "")
    finally:
        reponse.dispose()


def _dans_la_page(page: Page, url: str) -> tuple[bytes, str]:
    data_url = page.evaluate(LIRE_DANS_LA_PAGE, url)
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        raise MediaIllisible("lecture dans la page impossible")
    return decoder_data_url(data_url)


def _capture(page: Page, repere: int) -> tuple[bytes, str]:
    element = page.locator(f"[{MARQUE}='{int(repere)}']").first
    return element.screenshot(type="png", timeout=10_000), "image/png"
