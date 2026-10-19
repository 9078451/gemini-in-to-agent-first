"""Le pilote de site dans un vrai Chrome (sans fenêtre), sur une fausse page de chat locale :
taper, envoyer, lire la réponse au fil de l'eau, l'arrêter. Ignoré si Chrome est absent."""
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import config
from pilote.erreurs import Interrompu, PasConnecteSite
from pilote.site import PiloteSite
from pilote.sites import ProfilSite

pytestmark = pytest.mark.skipif(not Path(config.CHEMIN_CHROME).exists(), reason="Chrome absent")

PAGE = """<!doctype html><meta charset="utf-8"><title>Faux chat</title>
<div id="fil"></div>
<textarea id="prompt-textarea"></textarea>
<button aria-label="Envoyer un message" id="envoyer">Envoyer</button>
<script>
document.getElementById('envoyer').onclick = () => {
  const champ = document.getElementById('prompt-textarea');
  const texte = champ.value;
  if (!texte) return;
  champ.value = '';
  const q = document.createElement('div');
  q.setAttribute('data-message-author-role', 'user');
  q.textContent = texte;
  fil.append(q);
  const stop = document.createElement('button');
  stop.setAttribute('data-testid', 'stop-button');
  stop.textContent = 'Arrêter';
  document.body.append(stop);
  const r = document.createElement('div');
  r.setAttribute('data-message-author-role', 'assistant');
  const md = document.createElement('div');
  md.className = 'markdown';
  r.append(md);
  let i = 0, minuteur;
  const mots = ('Réponse à : ' + texte + ' un deux trois quatre fin').split(' ');
  stop.onclick = () => { clearInterval(minuteur); stop.remove(); window.arrete = true; };
  setTimeout(() => {
    fil.append(r);
    minuteur = setInterval(() => {
      md.innerHTML = '<p>' + mots.slice(0, ++i).join(' ') + '</p><button>Copier</button>';
      if (i >= mots.length) { clearInterval(minuteur); stop.remove(); history.pushState({}, '', '/c/abc'); }
    }, 120);
  }, 300);
};
</script>"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("site")
    (dossier / "index.html").write_text(PAGE, encoding="utf-8")
    (dossier / "login").mkdir()
    (dossier / "login" / "index.html").write_text("<p>Connexion</p>", encoding="utf-8")
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(dossier)))
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{serveur.server_address[1]}"
    serveur.shutdown()


@pytest.fixture(scope="module")
def navigateur():
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        chrome = playwright.chromium.launch(executable_path=str(config.CHEMIN_CHROME), headless=True)
    except Exception as e:  # Chrome présent mais refuse de démarrer sans fenêtre
        playwright.stop()
        pytest.skip(f"Chrome sans fenêtre impossible : {e}")
    yield chrome
    chrome.close()
    playwright.stop()


class Onglet:
    def __init__(self, page):
        self._page = page

    def page(self):
        return self._page


def pilote(site, navigateur, tmp_path):
    profil = ProfilSite(
        id="faux", nom="Faux chat", url_nouvelle=f"{site}/", prefixe=site,
        reperes={
            "champ_saisie": ["#prompt-textarea"], "bouton_envoyer": ["button[aria-label='Envoyer un message']"],
            "question": ["[data-message-author-role='user']"], "reponse": ["[data-message-author-role='assistant']"],
            "generation": ["button[data-testid='stop-button']"], "limite": [], "connexion": [],
        },
        html={"contenu": ".markdown", "code": "pre", "entete": ".__aucun__", "decor": "button, svg", "texte_contenu": True},
        pages_connexion=("/login",),
    )
    page = navigateur.new_page()
    return PiloteSite(Onglet(page), profil, delai_reponse=20, stabilite=1.0, dossier_captures=tmp_path), page


def test_envoi_et_reponse_au_fil(site, navigateur, tmp_path):
    p, page = pilote(site, navigateur, tmp_path)
    vus = []
    r = p.envoyer(None, "Bonjour", au_fil=lambda texte, html: vus.append(texte))
    assert r.reponse == "Réponse à : Bonjour un deux trois quatre fin"
    assert r.adresse.endswith("/c/abc")
    assert "<p>Réponse à : Bonjour un deux trois quatre fin</p>" in r.html and "Copier" not in r.html
    assert len({v for v in vus if v}) >= 3  # le texte a été vu grandir
    page.close()


def test_arret_clique_sur_arreter_et_garde_le_debut(site, navigateur, tmp_path):
    p, page = pilote(site, navigateur, tmp_path)

    def au_fil(texte, html):
        if texte.count(" ") >= 4:  # « Réponse à : Salut un » : la page écrit encore
            raise Interrompu(texte, html)

    with pytest.raises(Interrompu) as erreur:
        p.envoyer(None, "Salut", au_fil=au_fil)
    assert erreur.value.partiel.startswith("Réponse à :")
    assert page.evaluate("window.arrete") is True
    page.close()


def test_page_de_connexion(site, navigateur, tmp_path):
    p, page = pilote(site, navigateur, tmp_path)
    with pytest.raises(PasConnecteSite):
        p.envoyer(f"{site}/login/", "Bonjour")
    page.close()
