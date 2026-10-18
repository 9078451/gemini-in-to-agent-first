"""Le pilote face à une fausse page Gemini, dans un vrai Chromium : médias repérés,
attendus et téléchargés (avec les cookies de la page, depuis un blob, en taille réelle),
fichiers joints (collés, ou choisis avec « + »), réponse lue en direct, puis arrêtée.

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
<div class="saisie">
<div id="pieces"></div>
<rich-textarea><div class="ql-editor" contenteditable="true"></div></rich-textarea>
<button aria-label="Ouvrir le menu d'importation de fichiers" id="plus">+</button>
<div role="menu" id="menu-import" hidden><button role="menuitem" id="importer">Importer des fichiers</button></div>
<button aria-label="Outils" id="outils">Outils</button>
<div role="menu" id="menu" hidden>
  <button role="menuitemcheckbox" aria-checked="false">Deep Research</button>
  <button role="menuitemcheckbox" aria-checked="false" data-outil="video">Créer des vidéos (Veo 3.1)</button>
  <button role="menuitemcheckbox" aria-checked="false" data-outil="image">Créer des images</button>
</div>
<button aria-label="Envoyer un message" id="envoyer">Envoyer</button>
</div>
<button aria-label="Interrompre la réponse" id="stop" hidden>Stop</button>
<script>
window.recus = [];  // fichiers joints au message envoyé
window.collageIgnore = false;  // comme une page qui ne prend pas les fichiers collés ni déposés
const pieces = document.getElementById("pieces");
const accueillir = async (liste) => {
  for (const f of liste) {
    const apercu = document.createElement("div");
    apercu.className = "file-preview";
    apercu.dataset.nom = f.name; apercu.dataset.taille = f.size; apercu.dataset.type = f.type;
    apercu.innerHTML = '<span role="progressbar">envoi…</span>' + f.name;
    pieces.append(apercu);
    setTimeout(() => apercu.querySelector("[role=progressbar]").remove(), 700);  // envoi à Google
  }
};
const editeur = document.querySelector(".ql-editor");
editeur.addEventListener("paste", (e) => {
  if (window.collageIgnore || !e.clipboardData.files.length) return;
  e.preventDefault(); accueillir([...e.clipboardData.files]);
});
editeur.addEventListener("drop", (e) => {
  if (window.collageIgnore) return;
  e.preventDefault(); accueillir([...e.dataTransfer.files]);
});
const menuImport = document.getElementById("menu-import");
document.getElementById("plus").onclick = () => { menuImport.hidden = false; };
// Comme Gemini : le champ de fichier n'existe qu'au moment de l'import.
document.getElementById("importer").onclick = () => {
  menuImport.hidden = true;
  const champ = document.createElement("input");
  champ.type = "file";
  champ.onchange = (e) => { accueillir([...e.target.files]); champ.remove(); };
  champ.click();
};
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
  window.recus = [...pieces.children].map((p) => ({nom: p.dataset.nom, taille: +p.dataset.taille, type: p.dataset.type}));
  pieces.replaceChildren();
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
  } else if (texte.includes("longue")) {
    window.arretee = false;
    stop.onclick = () => { window.arretee = true; stop.hidden = true; };
    for (const mot of "Il était une fois un très long conte qui ne finissait jamais".split(" ")) {
      if (window.arretee) return;
      md.textContent += (md.textContent ? " " : "") + mot;
      await attendre(250);
    }
    stop.hidden = true;
  } else if (window.recus.length) {
    md.innerHTML = "<p>J'ai reçu " + window.recus.map((f) => f.nom).join(", ") + ".</p>";
    stop.hidden = true;
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
            "/c": (PAGE_CHATGPT.encode(), "text/html; charset=utf-8"),
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
    import pilote.pieces as pieces

    monkeypatch.setattr(pieces, "_ORDRES", {})

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


def test_photo_collee_jointe_au_message(pilote):
    from pilote.modeles import Media

    pilote, _ = pilote
    resultat = pilote.envoyer(None, "Que vois-tu ?", pieces=(Media("image", "image/png", PETITE, "vacances.png"),))
    recus = pilote._onglet.page().evaluate("window.recus")
    assert recus == [{"nom": "vacances.png", "taille": len(PETITE), "type": "image/png"}]
    assert resultat.reponse == "J'ai reçu vacances.png."


def test_fichier_choisi_avec_plus_quand_le_collage_est_ignore(pilote):
    from pilote.modeles import Media

    pilote, _ = pilote
    page = pilote._onglet.page()
    page.evaluate("window.collageIgnore = true")
    pdf = b"%PDF-1.4 faux"
    pilote.envoyer(None, "Résume", pieces=(Media("fichier", "application/pdf", pdf, "rapport.pdf"),))
    # une seule fois, malgré trois façons d'essayer
    assert page.evaluate("window.recus") == [{"nom": "rapport.pdf", "taille": len(pdf), "type": "application/pdf"}]


def test_piece_refusee_erreur_claire(pilote):
    from pilote.erreurs import PieceRefusee
    from pilote.modeles import Media

    pilote, _ = pilote
    page = pilote._onglet.page()
    page.evaluate("window.collageIgnore = true; document.getElementById('plus').remove()")
    with pytest.raises(PieceRefusee):
        pilote.envoyer(None, "x", pieces=(Media("image", "image/png", PETITE, "a.png"),))
    assert page.evaluate("document.querySelectorAll('user-query').length") == 0  # rien n'est parti


def test_reponse_lue_en_direct_puis_arretee(pilote):
    import threading

    pilote, _ = pilote
    vus, arret = [], threading.Event()

    def au_fil(texte):
        vus.append(texte)
        if len(texte.split()) >= 4:
            arret.set()

    resultat = pilote.envoyer(None, "Raconte une longue histoire", au_fil=au_fil, arret=arret)
    assert resultat.interrompue and resultat.reponse.startswith("Il était une fois")
    assert len(resultat.reponse.split()) < 12  # le conte n'est pas allé au bout
    assert pilote._onglet.page().evaluate("window.arretee") is True  # « Interrompre » cliqué dans Gemini
    # chaque lecture prolonge la précédente : le client voit le texte s'écrire
    assert len(vus) >= 2 and all(b.startswith(a) for a, b in zip(vus, vus[1:]))


def test_champ_de_fichier_de_la_page(pilote):
    # Comme ChatGPT : un champ de fichier caché, toujours là.
    from pilote.modeles import Media

    pilote, _ = pilote
    page = pilote._onglet.page()
    page.evaluate("""() => {
      window.collageIgnore = true;
      const champ = document.createElement('input');
      champ.type = 'file'; champ.hidden = true; champ.accept = 'image/*,.pdf';
      champ.onchange = (e) => accueillir([...e.target.files]);
      document.querySelector('.saisie').append(champ);
    }""")
    pilote.envoyer(None, "Lis", pieces=(Media("fichier", "application/pdf", b"%PDF", "a.pdf"),))
    assert page.evaluate("window.recus") == [{"nom": "a.pdf", "taille": 4, "type": "application/pdf"}]


# ---- un autre site, même pilote : une fausse page « à la ChatGPT » ----------------

PAGE_CHATGPT = """<!doctype html><meta charset="utf-8"><title>Faux ChatGPT</title>
<body>
<button data-testid="model-switcher-dropdown-button" aria-haspopup="menu" id="bouton-modele">ChatGPT Auto</button>
<div role="menu" id="menu-modeles" hidden>
  <div role="menuitem" data-testid="model-switcher-auto" aria-checked="true"><div>Auto</div><div>Choisit pour toi</div></div>
  <div role="menuitem" data-testid="model-switcher-instant" aria-checked="false"><div>Instant</div><div>Répond tout de suite</div></div>
  <div role="menuitem" data-testid="model-switcher-thinking" aria-checked="false"><div>Thinking</div><div>Réfléchit plus longtemps</div></div>
</div>
<main id="fil"></main>
<form><div id="prompt-textarea" contenteditable="true"></div><input type="file" hidden multiple id="champ-fichier">
<div id="pieces"></div><button type="button" data-testid="send-button">Envoyer</button></form>
<button data-testid="stop-button" hidden>Arrêter</button>
<script>
document.cookie = "session=ok; path=/";
window.modele = "Auto"; window.recus = [];
const menu = document.getElementById("menu-modeles");
document.getElementById("bouton-modele").onclick = () => { menu.hidden = !menu.hidden; };
menu.querySelectorAll("[role=menuitem]").forEach((item) => item.onclick = () => {
  menu.querySelectorAll("[role=menuitem]").forEach((i) => i.setAttribute("aria-checked", String(i === item)));
  window.modele = item.firstElementChild.textContent;
  document.getElementById("bouton-modele").textContent = "ChatGPT " + window.modele;
  menu.hidden = true;
});
document.getElementById("champ-fichier").onchange = (e) => {
  for (const f of e.target.files) {
    const puce = document.createElement("div"); puce.textContent = f.name; document.getElementById("pieces").append(puce);
    window.recus.push(f.name);
  }
};
const stop = document.querySelector("[data-testid=stop-button]");
const attendre = (ms) => new Promise((ok) => setTimeout(ok, ms));
let tour = 0;
document.querySelector("[data-testid=send-button]").onclick = async () => {
  const champ = document.getElementById("prompt-textarea");
  const texte = champ.innerText; champ.innerText = "";
  document.getElementById("pieces").replaceChildren();
  const fil = document.getElementById("fil");
  fil.insertAdjacentHTML("beforeend", `<article data-testid="conversation-turn-${++tour}"><div data-message-author-role="user">${texte}</div></article>`);
  stop.hidden = false;
  await attendre(300);
  const article = document.createElement("article");
  article.dataset.testid = `conversation-turn-${++tour}`;
  article.innerHTML = '<h6 class="sr-only">ChatGPT a dit :</h6><div data-message-author-role="assistant"><div class="markdown prose"></div></div>';
  fil.append(article);
  const md = article.querySelector(".markdown");
  if (texte.includes("limite")) {
    md.innerHTML = "<p>You've reached our limit of messages per hour. Please try again later.</p>";
  } else if (texte.includes("image")) {
    md.innerHTML = "<p>Image créée.</p>";
    article.querySelector("[data-message-author-role]").insertAdjacentHTML("beforeend", '<img src="/fichiers/chat.png" alt="Image générée" width="300" height="300">');
  } else {
    md.innerHTML = `<p>Réponse de ${window.modele}${window.recus.length ? " avec " + window.recus.join(", ") : ""}.</p>`
      + '<pre><div><div class="entete">python</div><div class="sticky"><button>Copier le code</button></div>'
      + '<div><code class="language-python">print(1)</code></div></div></pre>';
  }
  window.recus = [];
  await attendre(200);
  stop.hidden = true;
};
</script>"""


@pytest.fixture
def pilote_chatgpt(navigateur, tmp_path, monkeypatch):
    import dataclasses

    import pilote.pieces as pieces
    from pilote.sites import CHATGPT

    monkeypatch.setattr(pieces, "_ORDRES", {})
    serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Serveur)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{serveur.server_address[1]}"
    site = dataclasses.replace(CHATGPT, url=f"{base}/c", prefixe=base)
    contexte = navigateur.new_context()
    page = contexte.new_page()
    page.goto(f"{base}/c")
    yield PiloteGemini(Onglet(page), f"{base}/c", 30.0, 0.3, tmp_path, site=site)
    contexte.close()
    serveur.shutdown()


def test_autre_site_modele_choisi_texte_et_html_propres(pilote_chatgpt):
    modes = pilote_chatgpt.lister_modes()
    assert [(o.nom, o.description, o.actif) for o in modes.modeles] == [
        ("Auto", "Choisit pour toi", True), ("Instant", "Répond tout de suite", False),
        ("Thinking", "Réfléchit plus longtemps", False)]
    assert modes.niveaux == []
    resultat = pilote_chatgpt.envoyer(None, "Bonjour", modele="Thinking")
    assert pilote_chatgpt._onglet.page().evaluate("window.modele") == "Thinking"
    assert resultat.modele == "Thinking"
    assert resultat.reponse.startswith("Réponse de Thinking.") and "Copier le code" not in resultat.reponse
    assert '<pre data-langue="python"><code class="language-python">print(1)</code></pre>' in resultat.html
    assert "Copier" not in resultat.html and "ChatGPT a dit" not in resultat.reponse


def test_autre_site_fichier_joint_par_son_champ(pilote_chatgpt):
    from pilote.modeles import Media

    resultat = pilote_chatgpt.envoyer(None, "Lis", pieces=(Media("fichier", "application/pdf", b"%PDF", "note.pdf"),))
    assert "avec note.pdf" in resultat.reponse


def test_autre_site_limite_reconnue(pilote_chatgpt):
    from pilote.erreurs import LimiteAtteinte

    with pytest.raises(LimiteAtteinte) as erreur:
        pilote_chatgpt.envoyer(None, "dépasse la limite")
    assert erreur.value.site == "ChatGPT" and "reached our limit" in erreur.value.detail


def test_autre_site_image_creee(pilote_chatgpt):
    resultat = pilote_chatgpt.envoyer(None, "une image de chat", outil="image")
    assert [(m.type, m.mime) for m in resultat.medias] == [("image", "image/png")]


def test_autre_site_pas_connecte(pilote_chatgpt):
    from pilote.erreurs import PasConnecteGoogle

    page = pilote_chatgpt._onglet.page()
    page.evaluate("""() => document.body.insertAdjacentHTML('beforeend', '<button data-testid="login-button">Se connecter</button>')""")
    assert pilote_chatgpt.est_connecte() is False
    with pytest.raises(PasConnecteGoogle) as erreur:
        pilote_chatgpt.envoyer(None, "Bonjour")
    assert "OpenAI" in str(erreur.value)
