"""Joindre des fichiers (photos, PDF, sons…) à un message, dans la zone de saisie du site.

Quatre façons, essayées dans l'ordre pour chaque fichier : le coller (comme Ctrl+V), le
déposer (glisser-déposer), le confier au champ de fichier de la page (ChatGPT en a un),
le choisir avec le bouton « + » (sélecteur de fichiers intercepté : aucune fenêtre de
Windows ne s'ouvre). Un fichier compte comme joint quand son aperçu (ou son nom) apparaît
à côté du texte ; le message part une fois les envois au site finis.
"""
import base64
import logging
import re
import time

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as DelaiPlaywright

from pilote.erreurs import ErreurPilote, PieceRefusee
from pilote.modeles import Media
from pilote.reperes import premier_present
from pilote.selecteurs import ENTREE_IMPORTER
from pilote.sites import GEMINI, Site

journal = logging.getLogger(__name__)

ATTENTE_APERCU = 3.0  # s : apparition de l'aperçu après un essai
DELAI_TELEVERSEMENT = 180.0  # s : envoi des fichiers joints au site

_ZONE = """
const visible = (e) => (e.checkVisibility ? e.checkVisibility() : !!e.offsetParent);
const zone = (s) => {
  const champ = s.champs.map((c) => document.querySelector(c)).find(Boolean);
  if (!champ) return null;
  const autour = s.zone ? champ.closest(s.zone) : null;
  if (autour) return {champ, zone: autour};
  const envoyer = s.envoyer.map((c) => document.querySelector(c)).find(Boolean);
  let z = champ.parentElement;
  for (let i = 0; z && z.parentElement && i < 8; i++, z = z.parentElement) {
    if (envoyer ? z.contains(envoyer) && i >= 1 : i >= 4) break;
  }
  return {champ, zone: z || champ.parentElement};
};
"""

# Aperçus des fichiers joints : hors du texte tapé, un seul par fichier (le plus extérieur).
COMPTER = "(s) => {" + _ZONE + """
  const z = zone(s);
  if (!z) return 0;
  const dedans = [...z.zone.querySelectorAll(s.pieces)].filter((e) => !z.champ.contains(e) && visible(e));
  return dedans.filter((e) => !dedans.some((autre) => autre !== e && autre.contains(e))).length;
}"""

# Le nom d'un fichier affiché à côté du texte (puce « rapport.pdf » sans aperçu reconnu).
NOM_AFFICHE = "(s) => {" + _ZONE + """
  const z = zone(s);
  if (!z) return false;
  return [...z.zone.querySelectorAll('*')].some((e) => !z.champ.contains(e) && e.children.length === 0
    && (e.textContent || '').includes(s.nom));
}"""

EN_COURS = "(s) => {" + _ZONE + """
  const z = zone(s);
  return !!z && [...z.zone.querySelectorAll(s.en_cours)].some((e) => !z.champ.contains(e) && visible(e));
}"""

_FICHIERS = """
const fichiers = (liste) => {
  const dt = new DataTransfer();
  for (const f of liste) {
    const octets = Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0));
    dt.items.add(new File([octets], f.nom, {type: f.mime}));
  }
  return dt;
};
"""

COLLER = "(s) => {" + _ZONE + _FICHIERS + """
  const z = zone(s);
  if (!z) return false;
  z.champ.focus();
  z.champ.dispatchEvent(new ClipboardEvent('paste', {clipboardData: fichiers(s.fichiers), bubbles: true, cancelable: true}));
  return true;
}"""

DEPOSER = "(s) => {" + _ZONE + _FICHIERS + """
  const z = zone(s);
  if (!z) return false;
  const dt = fichiers(s.fichiers);
  for (const type of ['dragenter', 'dragover', 'drop']) {
    z.champ.dispatchEvent(new DragEvent(type, {dataTransfer: dt, bubbles: true, cancelable: true}));
  }
  return true;
}"""


def nom_de(piece: Media, rang: int) -> str:
    """Le nom du fichier montré à Gemini (il en tient compte : « rapport.pdf »)."""
    if piece.description and re.fullmatch(r"[^\\/:*?\"<>|]{1,120}\.[A-Za-z0-9]{1,6}", piece.description):
        return piece.description
    extension = piece.mime.split("/")[-1].split("+")[0].split(";")[0]
    extension = {"jpeg": "jpg", "plain": "txt", "mpeg": "mp3"}.get(extension, extension)
    return f"piece-{rang}.{re.sub(r'[^a-z0-9]', '', extension.lower()) or 'bin'}"


def joindre(page: Page, pieces: list[Media], site: Site = GEMINI) -> None:
    """Joint chaque fichier à la saisie. PieceRefusee si l'un n'apparaît pas ; attend ensuite
    que leur envoi au site soit fini (ErreurPilote au-delà de DELAI_TELEVERSEMENT)."""
    ordre = _ORDRES.setdefault(site.nom, list(_METHODES))
    for rang, piece in enumerate(pieces, 1):
        nom = nom_de(piece, rang)
        avant = compter_pieces(page, site)
        joint = False
        for methode in list(ordre):
            try:
                if methode(page, piece, nom, site) and _attendre_apercu(page, avant, nom, site):
                    joint = True
            except ErreurPlaywright as e:
                journal.info("Pièce jointe « %s » : %s a échoué (%s)", nom, methode.__name__, str(e).splitlines()[0])
            # Un aperçu arrivé en retard compte : ne jamais joindre deux fois le même fichier.
            if joint or _apparue(page, avant, nom, site):
                ordre.remove(methode)
                ordre.insert(0, methode)  # la façon qui a marché passe en premier la prochaine fois
                break
        else:
            raise PieceRefusee(nom)
    attendre_televersement(page, site=site)


def compter_pieces(page: Page, site: Site = GEMINI) -> int:
    return int(page.evaluate(COMPTER, _parametres(site)))


def attendre_televersement(page: Page, delai: float = DELAI_TELEVERSEMENT, site: Site = GEMINI) -> None:
    fin = time.monotonic() + delai
    time.sleep(0.3)  # l'indicateur d'envoi peut apparaître juste après l'aperçu
    while page.evaluate(EN_COURS, _parametres(site)):
        if time.monotonic() >= fin:
            raise ErreurPilote(
                f"Les fichiers joints ne finissent pas de s'envoyer à {site.libelle} après {delai:.0f} s : "
                "vérifie ta connexion, ou joins des fichiers plus légers."
            )
        time.sleep(0.5)


def _parametres(site: Site, piece: Media | None = None, nom: str = "") -> dict:
    parametres = {
        "champs": site.reperes["champ_saisie"], "envoyer": site.reperes.get("bouton_envoyer", []),
        "pieces": site.pieces_saisie, "en_cours": site.televersement, "zone": site.zone_saisie, "nom": nom,
    }
    if piece is not None:
        parametres["fichiers"] = [{"nom": nom, "mime": piece.mime, "b64": base64.b64encode(piece.donnees).decode("ascii")}]
    return parametres


def _apparue(page: Page, avant: int, nom: str, site: Site) -> bool:
    return compter_pieces(page, site) > avant or bool(page.evaluate(NOM_AFFICHE, _parametres(site, nom=nom)))


def _attendre_apercu(page: Page, avant: int, nom: str, site: Site) -> bool:
    fin = time.monotonic() + ATTENTE_APERCU
    while time.monotonic() < fin:
        if _apparue(page, avant, nom, site):
            return True
        time.sleep(0.25)
    return False


def _coller(page: Page, piece: Media, nom: str, site: Site) -> bool:
    return bool(page.evaluate(COLLER, _parametres(site, piece, nom)))


def _deposer(page: Page, piece: Media, nom: str, site: Site) -> bool:
    return bool(page.evaluate(DEPOSER, _parametres(site, piece, nom)))


def _champ_fichier(page: Page, piece: Media, nom: str, site: Site) -> bool:
    """Le champ de fichier caché de la page, s'il en a un qui accepte ce type."""
    champs = page.locator("input[type='file']")
    for i in range(champs.count()):
        accepte = (champs.nth(i).get_attribute("accept") or "").lower()
        famille = piece.mime.split("/")[0] + "/*"
        if not accepte or any(a.strip() in (piece.mime, famille, "*/*") or nom.lower().endswith(a.strip())
                              for a in accepte.split(",")):
            champs.nth(i).set_input_files({"name": nom, "mimeType": piece.mime, "buffer": piece.donnees})
            return True
    return False


def _par_selecteur(page: Page, piece: Media, nom: str, site: Site) -> bool:
    """Le bouton « + » ouvre le sélecteur de fichiers, tout de suite ou par son menu."""
    bouton = premier_present(page, "bouton_importer", site.reperes)
    if bouton is None:
        return False
    fichier = {"name": nom, "mimeType": piece.mime, "buffer": piece.donnees}
    try:
        with page.expect_file_chooser(timeout=1500) as choix:
            bouton.first.click(timeout=3000)
        choix.value.set_files(fichier)
        return True
    except DelaiPlaywright:
        pass
    entree = page.get_by_role("menuitem", name=re.compile(ENTREE_IMPORTER, re.IGNORECASE)).filter(visible=True)
    if entree.count() == 0:
        page.keyboard.press("Escape")
        return False
    try:
        with page.expect_file_chooser(timeout=4000) as choix:
            entree.first.click(timeout=3000)
        choix.value.set_files(fichier)
        return True
    except DelaiPlaywright:
        page.keyboard.press("Escape")  # un autre sélecteur (Google Drive…) s'est ouvert
        return False


_METHODES = (_coller, _deposer, _champ_fichier, _par_selecteur)
_ORDRES: dict[str, list] = {}  # par site : la façon qui a marché en tête
