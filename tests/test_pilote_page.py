"""Le pilote face à une fausse page Gemini, dans un vrai Chromium : médias repérés,
attendus et téléchargés (avec les cookies de la page, depuis un blob, en taille réelle).

Lancé avec le Chromium de Playwright, sinon celui de AGENT_FIRST_CHROMIUM, sinon le Chrome
de `config` ; passé si aucun ne démarre.
"""
import http.server
import os
import struct
import threading
import zlib

import pytest

from pilote.gemini import PiloteGemini
from pilote.medias import deviner_mime, variantes

PAGE = """<!doctype html><meta charset="utf-8"><title>Faux Gemini</title>
<body>
<div id="fil"></div>
<rich-textarea><div class="ql-editor" contenteditable="true"></div></rich-textarea>
<button aria-label="Outils" id="outils">Outils</button>
<div role="menu" id="menu" hidden>
  <button role="menuitemcheckbox" aria-checked="false">Deep Research</button>
  <button role="menuitemcheckbox" aria-checked="false" data-outil="video">Créer des vidéos (Veo 3.1)</button>
  <button role="menuitemcheckbox" aria-checked="false" data-outil="image">Créer des images</button>
</div>
<button aria-label="Envoyer un message" id="envoyer">Envoyer</button>
<button aria-label="Interrompre la réponse" id="stop" hidden>Stop</button>
<script>
document.cookie = "session=ok; path=/";
window.outil = null;
const menu = document.getElementById("menu");
document.getElementById("outils").onclick = () => { menu.hidden = !menu.hidden; };
menu.onclick = (e) => {
  const b = e.target.closest("[role=menuitemcheckbox]");
  b.setAttribute("aria-checked", "true"); window.outil = b.dataset.outil || "autre"; menu.hidden = true;
};
const stop = document.getElementById("stop");
const attendre = (ms) => new Promise((ok) => setTimeout(ok, ms));
document.getElementById("envoyer").onclick = async () => {
  const champ = document.querySelector(".ql-editor");
  const texte = champ.innerText; champ.innerText = "";
  const q = document.createElement("user-query"); q.textContent = texte;
  document.getElementById("fil").append(q);
  stop.hidden = false;
  await attendre(300);
  const r = document.createElement("model-response");
  r.innerHTML = '<message-content><div class="markdown"></div></message-content>';
  document.getElementById("fil").append(r);
  const md = r.querySelector(".markdown");
  if (texte.includes("image")) {
    md.innerHTML = "<p>Gemini a dit</p><p>Voici ton image.</p>";
    r.insertAdjacentHTML("beforeend", '<generated-image><img src="/fichiers/chat.png=s1024-rj" alt="un chat roux" width="256" height="256"></generated-image>'
      + '<img src="/fichiers/chat.png" width="16" height="16" alt="icône">');
    stop.hidden = true;
  } else if (texte.includes("vidéo")) {
    md.innerHTML = "<p>Je crée ta vidéo, cela peut prendre une minute…</p>";
    stop.hidden = true;  // le texte est fini, la vidéo pas encore
    r.insertAdjacentHTML("beforeend", '<div class="chargement" role="progressbar">…</div>');
    await attendre(1500);
    r.querySelector(".chargement").remove();
    r.insertAdjacentHTML("beforeend", '<video controls src="/fichiers/clip.mp4"></video>');
  } else if (texte.includes("blob")) {
    const b = await (await fetch("/fichiers/chat.png")).blob();
    r.insertAdjacentHTML("beforeend", `<img src="${URL.createObjectURL(b)}" width="200" height="200">`);
    stop.hidden = true;  // une image seule, sans texte
  } else {
    md.innerHTML = "<p>Bonjour !</p>";
    stop.hidden = true;
  }
};
</script>"""


def png(largeur: int, hauteur: int) -> bytes:
    def morceau(nom, donnees):
        return struct.pack(">I", len(donnees)) + nom + donnees + struct.pack(">I", zlib.crc32(nom + donnees))
    lignes = b"".join(b"\x00" + b"\xff\x00\x00" * largeur for _ in range(hauteur))
    return (b"\x89PNG\r\n\x1a\n" + morceau(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0))
            + morceau(b"IDAT", zlib.compress(lignes)) + morceau(b"IEND", b""))


PETITE, GRANDE = png(4, 4), png(8, 8)
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64


class Serveur(http.server.BaseHTTPRequestHandler):
    vus: list[str] = []

    def do_GET(self):
        Serveur.vus.append(self.path)
        if self.path.startswith("/fichiers/") and "session=ok" not in (self.headers.get("Cookie") or ""):
            return self._repondre(403, b"interdit", "text/plain")  # comme un fichier lié au compte Google
        fichiers = {
            "/app": (PAGE.encode(), "text/html; charset=utf-8"),
            "/fichiers/chat.png": (PETITE, "image/png"),
            "/fichiers/chat.png=s1024-rj": (PETITE, "image/png"),
            "/fichiers/chat.png=s0": (GRANDE, "image/png"),
            "/fichiers/clip.mp4": (MP4, "application/octet-stream"),  # en-tête trompeur : les octets décident
        }
        if self.path not in fichiers:
            return self._repondre(404, b"absent", "text/plain")
        self._repondre(200, *fichiers[self.path])

    def _repondre(self, code, corps, type_):
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *args):
        pass


class Onglet:
    def __init__(self, page):
        self._page = page

    def page(self):
        return self._page


@pytest.fixture(scope="module")
def navigateur():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        playwright = sync_api.sync_playwright().start()
    except Exception as e:
        pytest.skip(f"Playwright indisponible : {e}")
    import config

    navigateur, raisons = None, []
    for chemin in (None, os.environ.get("AGENT_FIRST_CHROMIUM"), str(config.CHEMIN_CHROME)):
        if chemin is not None and not os.path.exists(chemin):
            continue
        try:
            navigateur = playwright.chromium.launch(executable_path=chemin)
            break
        except Exception as e:
            raisons.append(str(e).splitlines()[0])
    if navigateur is None:
        playwright.stop()
        pytest.skip(f"Chromium indisponible : {' ; '.join(raisons)}")
    yield navigateur
    navigateur.close()
    playwright.stop()


@pytest.fixture
def pilote(navigateur, tmp_path, monkeypatch):
    import pilote.medias as medias

    serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Serveur)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{serveur.server_address[1]}"
    # La fausse page n'est pas sur googleusercontent.com : la taille réelle est essayée quand même.
    monkeypatch.setattr(medias, "variantes", lambda url, type_media: (
        [url.split("=")[0] + "=s0", url] if type_media == "image" and "=" in url else [url]))
    contexte = navigateur.new_context()
    page = contexte.new_page()
    page.goto(f"{base}/app")
    Serveur.vus.clear()
    yield PiloteGemini(Onglet(page), f"{base}/app", 30.0, 0.3, tmp_path), base
    contexte.close()
    serveur.shutdown()


def test_reponse_ecrite_sans_media(pilote):
    pilote, _ = pilote
    resultat = pilote.envoyer(None, "Bonjour")
    assert resultat.reponse == "Bonjour !" and resultat.medias == ()


def test_image_en_taille_reelle_avec_les_cookies(pilote):
    pilote, _ = pilote
    resultat = pilote.envoyer(None, "Génère une image d'un chat", outil="image")
    assert "Voici ton image." in resultat.reponse
    [media] = resultat.medias  # l'icône de 16 px n'est pas un média
    assert (media.type, media.mime, media.description) == ("image", "image/png", "un chat roux")
    assert media.donnees == GRANDE  # « =s0 » plutôt que l'image réduite affichée
    assert pilote._onglet.page().evaluate("window.outil") == "image"  # l'outil a été coché


def test_video_attendue_apres_le_texte(pilote):
    pilote, _ = pilote
    resultat = pilote.envoyer(None, "Génère une vidéo d'une vague", outil="video")
    assert [(m.type, m.mime) for m in resultat.medias] == [("video", "video/mp4")]
    assert resultat.medias[0].donnees == MP4 and resultat.duree >= 1.5
    assert pilote._onglet.page().evaluate("window.outil") == "video"


def test_image_seule_depuis_un_blob(pilote):
    pilote, _ = pilote
    resultat = pilote.envoyer(None, "montre un blob")
    assert resultat.reponse == "" and [m.donnees for m in resultat.medias] == [PETITE]


def test_outil_coche_puis_page_rechargee(pilote):
    pilote, base = pilote
    pilote.envoyer(None, "Génère une image", outil="image")
    pilote.envoyer(None, "Bonjour")
    # l'outil resterait coché : une discussion neuve est rechargée avant le message suivant
    assert pilote._onglet.page().evaluate("window.outil") is None


def test_deviner_mime_et_variantes():
    assert deviner_mime(PETITE, "", "image") == "image/png"
    assert deviner_mime(MP4, "application/octet-stream", "video") == "video/mp4"
    assert deviner_mime(MP4, "", "audio") == "audio/mp4"
    assert deviner_mime(b"ID3\x04", "", "audio") == "audio/mpeg"
    assert deviner_mime(b"\x1a\x45\xdf\xa3....", "", "video") == "video/webm"
    assert deviner_mime(b"<!doctype html>", "text/html", "image") is None  # page de connexion, pas une image
    assert deviner_mime(b"<svg/>", "image/svg+xml", "image") is None
    assert deviner_mime(b"????", "audio/x-custom", "audio") == "audio/x-custom"
    assert variantes("https://lh3.googleusercontent.com/gg/ABC=s1024-rj", "image") == [
        "https://lh3.googleusercontent.com/gg/ABC=s0", "https://lh3.googleusercontent.com/gg/ABC=s1024-rj"]
    assert variantes("https://lh3.googleusercontent.com/gg/ABC=s0", "image") == ["https://lh3.googleusercontent.com/gg/ABC=s0"]
    assert variantes("https://exemple.fr/a.png", "image") == ["https://exemple.fr/a.png"]
    assert variantes("https://lh3.googleusercontent.com/v=1", "video") == ["https://lh3.googleusercontent.com/v=1"]
