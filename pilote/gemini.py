"""Taper un message dans un assistant web (Gemini, ChatGPT, Claude…), attendre la fin de
la réponse et la lire. Même déroulé pour tous ; le profil du site (`sites.Site`) donne ses
adresses et ses repères."""
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote import medias, modes, modes_menu, outils, pieces as pieces_jointes
from pilote.attente import Interrompue, attendre_envoi, attendre_fin_reponse, attendre_nouvelle_reponse
from pilote.chrome import OngletGemini
from pilote.erreurs import (
    DelaiDepasse, ErreurPilote, LimiteAtteinte, LimiteGemini, PageInstable, PasConnecteGoogle, RepereIntrouvable,
    VerificationGoogle,
)
from pilote.modeles import Media, Modes, ResultatGemini
from pilote.reperes import attendre_repere, compter, premier_present
from pilote.sites import GEMINI, Site

journal = logging.getLogger(__name__)

# s : délai pour que la question apparaisse dans la conversation après le clic sur Envoyer.
# Large : quand le compte atteint sa limite, Gemini peut accepter le message en retard.
DELAI_ENVOI = 60.0
# s : après une réponse finie en apparence, attente d'un média encore en préparation ou
# demandé mais absent (une vidéo Veo arrive des minutes après « Je crée ta vidéo… »).
PATIENCE_MEDIAS = {None: 8.0, "image": 60.0, "video": 420.0, "musique": 240.0}

# Les blocs de texte de la réponse (les plus extérieurs), copiés ; dans chaque bloc de code,
# seul le code reste (langue gardée à part) ; le décor (boutons, icônes) est retiré.
EXTRAIRE_HTML = """(element, s) => {
  const blocs = [...element.querySelectorAll(s.contenu)];
  const exterieurs = blocs.filter((b) => !blocs.some((a) => a !== b && a.contains(b)));
  const copie = document.createElement('div');
  for (const b of (exterieurs.length ? exterieurs : [element])) copie.append(b.cloneNode(true));
  copie.querySelectorAll('pre').forEach((pre) => {
    const bloc = s.code ? pre.closest(s.code) : null;
    const entete = bloc && s.entete ? bloc.querySelector(s.entete) : null;
    const code = pre.querySelector('code');
    let langue = entete ? entete.innerText.trim().split('\\n')[0].trim() : '';
    if (!langue && code) langue = (code.className.match(/language-([\\w+#.-]+)/) || [])[1] || '';
    if (code && pre.firstElementChild !== code) pre.replaceChildren(code);
    if (langue) pre.setAttribute('data-langue', langue);
  });
  copie.querySelectorAll(s.decor).forEach((e) => e.remove());
  return copie.innerHTML;
}"""

# Le texte des blocs de la réponse, sans les lignes des boutons (« Copier le code »…).
LIRE_TEXTE = """(element, s) => {
  const blocs = [...element.querySelectorAll(s.contenu)];
  const exterieurs = blocs.filter((b) => !blocs.some((a) => a !== b && a.contains(b)));
  const texte = exterieurs.length ? exterieurs.map((b) => b.innerText).join('\\n\\n') : element.innerText;
  return texte.split('\\n').filter((l) => !s.lignes.includes(l.trim())).join('\\n');
}"""


def reglages_a_faire(
    dernier_modele: str | None, dernier_niveau: str | None, modele: str | None, niveau: str | None
) -> tuple[bool, bool]:
    """Quoi régler dans le sélecteur avant d'envoyer. Changer de modèle peut
    changer le niveau : le niveau demandé est alors réappliqué."""
    changer_modele = modele is not None and modele != dernier_modele
    changer_niveau = niveau is not None and (niveau != dernier_niveau or changer_modele)
    return changer_modele, changer_niveau


def nouvelle_discussion_prete(url_actuelle: str, url_nouvelle: str, questions_affichees: int) -> bool:
    """Vrai si la page est déjà une nouvelle discussion vide : inutile de la recharger
    (une ou deux secondes de gagnées, surtout après la préparation au démarrage)."""
    return url_actuelle.rstrip("/") == url_nouvelle.rstrip("/") and questions_affichees == 0


class ReglagesCompte:
    """Ce qu'une nouvelle discussion affiche : le dernier modèle et le dernier niveau
    choisis, dans n'importe quel onglet du compte. Une page déjà ouverte garde les siens,
    même quand l'autre onglet en change (vu en essai réel). Partagé par les pilotes : ils
    y notent chaque choix et savent ainsi, sans rouvrir le menu, ce qu'une discussion
    neuve affiche."""

    def __init__(self) -> None:
        self._verrou = threading.Lock()
        self._version = 0  # nombre de choix faits
        self._valeurs: tuple[str | None, str | None] | None = None  # None : pas encore connus

    def lire(self) -> tuple[int, tuple[str | None, str | None] | None]:
        with self._verrou:
            return self._version, self._valeurs

    def choix_en_cours(self) -> None:
        """Un onglet change de réglages : inconnus jusqu'à la fin de son choix (une discussion
        neuve ouverte entre-temps lit les siens), ou pour de bon s'il échoue à mi-chemin."""
        with self._verrou:
            self._version += 1
            self._valeurs = None

    def choisir(self, modele: str | None, niveau: str | None) -> None:
        with self._verrou:
            self._version += 1
            self._valeurs = (modele, niveau)

    def constater(self, version: int, modele: str | None, niveau: str | None) -> None:
        """Lus dans une discussion neuve chargée à `version` : ce sont ceux du compte,
        si personne n'a rien choisi depuis."""
        with self._verrou:
            if version == self._version:
                self._valeurs = (modele, niveau)


def limite_dans(reponse: str, question: str, site: Site) -> str | None:
    """La phrase de limite ou de saturation par laquelle le site a répondu, ou None. Seulement
    une réponse courte qui en commence par là, et que la question ne citait pas (« que veut
    dire “usage limit” ? » reçoit une vraie réponse)."""
    texte = " ".join(reponse.split())
    trouve = site.limite.search(texte[:300]) if texte and len(texte) < 500 else None
    if trouve is None or trouve.group(0).lower() in question.lower():
        return None
    return texte[:200]


class PiloteGemini:
    def __init__(
        self,
        onglet: OngletGemini,
        url_nouvelle: str,
        delai_reponse: float,
        stabilite: float,
        dossier_captures: Path,
        reglages: ReglagesCompte | None = None,
        site: Site = GEMINI,
    ) -> None:
        self._onglet = onglet
        self._site = site
        self._r = site.reperes
        self._url_nouvelle = url_nouvelle
        self._delai_reponse = delai_reponse
        self._stabilite = stabilite
        self._dossier_captures = dossier_captures
        # Réglages du sélecteur de la page pilotée, s'ils sont connus.
        self._modele: str | None = None
        self._niveau: str | None = None
        self._connus = False
        self._reglages = reglages or ReglagesCompte()
        self._page_suivie: Page | None = None
        # Version des réglages du compte quand la page a été chargée en discussion neuve
        # (elle les affichait alors), ou None.
        self._chargee_a: int | None = None
        self._message_parti = False  # le message en cours a été envoyé (pas de nouvel essai)
        # Un outil (image, vidéo…) a été coché : il resterait coché pour le message suivant,
        # la page est rechargée avant.
        self._outil_coche = False

    def envoyer(
        self,
        adresse: str | None,
        texte: str,
        modele: str | None = None,
        niveau: str | None = None,
        delai: float | None = None,
        outil: str | None = None,
        pieces: tuple[Media, ...] = (),
        au_fil: Callable[[str], None] | None = None,
        arret: threading.Event | None = None,
    ) -> ResultatGemini:
        """Envoie `texte` dans la conversation `adresse` (None = nouvelle conversation),
        après avoir réglé le modèle et le niveau demandés. `delai` remplace, pour ce
        message, la limite de temps de réponse par défaut. `outil` (« image », « video »,
        « musique ») coche l'outil de création de Gemini et attend le média. `pieces` :
        fichiers joints au message. `au_fil(texte)` reçoit la réponse pendant qu'elle
        s'écrit ; `arret` levé, la réponse est interrompue (`interrompue`, avec son début)."""
        for essai in (1, 2):
            page, self._message_parti = None, False
            try:
                page = self._page()
                return self._envoyer(
                    page, adresse, texte, modele, niveau, delai or self._delai_reponse, outil,
                    tuple(pieces), au_fil, arret,
                )
            except RepereIntrouvable as e:
                raise RepereIntrouvable(e.nom, self._capturer(page) if page else None) from e
            except ErreurPlaywright as e:
                # Onglet fermé ou rechargé, Chrome relancé… Avant l'envoi, un second essai suffit ;
                # après, le message est peut-être parti : le renvoyer en ferait un doublon.
                self._connus = False
                if self._message_parti or essai == 2:
                    raise PageInstable(str(e).splitlines()[0]) from e
                journal.warning("Page %s instable avant l'envoi, nouvel essai : %s", self._site.libelle, e)
        raise AssertionError("inatteignable")

    def preparer(self) -> None:
        """Ouvre Chrome et une nouvelle discussion, prête à recevoir un message
        (appelé au démarrage d'Agent First : le premier message n'attend plus Chrome)."""
        page = self._page()
        if not nouvelle_discussion_prete(page.url, self._url_nouvelle, compter(page, "question", self._r)):
            self._discussion_neuve(page)
        self._verifier_acces(page)
        attendre_repere(page, "champ_saisie", 30, self._r)

    def est_connecte(self) -> bool:
        return not self._demande_connexion(self._page())

    def lister_modes(self) -> Modes:
        page = self._page()
        if self._site.modes == "gemini":
            attendre_repere(page, "bouton_mode", 15, self._r)
        else:
            attendre_repere(page, "champ_saisie", 15, self._r)  # page prête ; un site sans sélecteur rend Modes([], [])
        return self._lire_reglages(page)

    def _envoyer(
        self, page: Page, adresse: str | None, texte: str, modele: str | None, niveau: str | None, delai: float,
        outil: str | None = None, pieces: tuple[Media, ...] = (), au_fil: Callable[[str], None] | None = None,
        arret: threading.Event | None = None,
    ) -> ResultatGemini:
        doit_arreter = arret.is_set if arret is not None else (lambda: False)
        recharger = self._outil_coche
        if adresse is None:
            if recharger or not nouvelle_discussion_prete(page.url, self._url_nouvelle, compter(page, "question", self._r)):
                self._discussion_neuve(page)
        elif recharger or page.url != adresse:
            page.goto(adresse, wait_until="domcontentloaded")
            self._conversation_rouverte()
            self._attendre_historique(page)
        self._outil_coche = False  # rechargée : plus d'outil coché (gardé si le rechargement a échoué)

        try:
            champ = attendre_repere(page, "champ_saisie", 15, self._r)
        except RepereIntrouvable:
            self._verifier_acces(page)
            raise
        self._verifier_acces(page)
        self._ajuster(page, modele, niveau)
        if outil is not None:
            self._outil_coche = True
            if not outils.choisir_outil(page, outil, self._site):
                journal.info("Outil « %s » introuvable dans %s : la demande part sans lui", outil, self._site.libelle)

        nb_avant = compter(page, "reponse", self._r)
        questions_avant = compter(page, "question", self._r)
        if pieces:  # avant le texte : vider la saisie retire une image que l'éditeur aurait collée dans le texte
            pieces_jointes.joindre(page, list(pieces), self._site)
        champ.first.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        # insert_text n'appuie sur aucune touche : les retours à la ligne
        # n'envoient pas le message en morceaux.
        page.keyboard.insert_text(texte)
        if doit_arreter():  # arrêtée avant l'envoi : rien n'est parti
            champ.first.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            return ResultatGemini(reponse="", adresse=page.url, modele=self._modele, niveau=self._niveau, interrompue=True)
        self._cliquer_envoyer(page, champ, bool(pieces))
        self._message_parti = True
        try:
            attendre_envoi(
                lambda: compter(page, "question", self._r), questions_avant, DELAI_ENVOI, lambda: self._bandeau_limite(page)
            )
        except ErreurPilote as e:
            # Vider le champ : sinon Gemini peut envoyer ce message plus tard, tout seul,
            # alors qu'Agent First a déjà abandonné.
            champ.first.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            if isinstance(e, LimiteGemini) and self._site is not GEMINI:
                raise LimiteAtteinte(self._site.libelle, e.detail) from e
            raise

        # Un seul délai pour tout le message : Gemini peut réfléchir longtemps
        # avant même d'afficher le début de sa réponse.
        debut = time.monotonic()
        fin = debut + delai
        nouvelle = None
        try:
            nouvelle = self._attendre_nouvelle_reponse(page, nb_avant, questions_avant + 1, delai, doit_arreter)
            reponse = attendre_fin_reponse(
                lire_texte=lambda: self._texte(nouvelle),
                generation_en_cours=lambda: self._generation_en_cours(page),
                delai_max=max(0.0, fin - time.monotonic()),
                stabilite=self._stabilite,
                lire_medias=lambda: medias.etat_medias(nouvelle, self._site),
                media_attendu=outil is not None,
                patience_medias=PATIENCE_MEDIAS.get(outil, PATIENCE_MEDIAS[None]),
                au_fil=au_fil,
                doit_arreter=doit_arreter,
            )
        except DelaiDepasse as e:
            raise DelaiDepasse(delai, e.partiel) from e  # le message cite la limite entière, pas le reste
        except Interrompue as e:
            return self._interrompre(page, nouvelle, e.partiel, round(time.monotonic() - debut, 1))
        duree = round(time.monotonic() - debut, 1)
        limite = limite_dans(reponse.replace("Gemini a dit", "", 1), texte, self._site)
        if limite:  # « Vous avez atteint votre limite… » à la place d'une réponse
            raise LimiteAtteinte(self._site.libelle, limite)
        trouves, perdus = medias.telecharger_medias(page, nouvelle, self._site)
        return ResultatGemini(
            reponse=reponse.strip(),
            adresse=page.url,
            html=self._html(nouvelle),
            modele=self._modele,
            niveau=self._niveau,
            duree=duree,
            medias=tuple(trouves),
            medias_perdus=perdus,
        )

    def _interrompre(self, page: Page, nouvelle: Locator | None, partiel: str, duree: float) -> ResultatGemini:
        """Clique « Interrompre la réponse » sur le site et rend ce qu'il avait déjà écrit."""
        bouton = premier_present(page, "bouton_arreter", self._r)
        if bouton is not None and bouton.first.is_visible():
            bouton.first.click(timeout=5000)
            time.sleep(0.5)  # le texte se fige
        if nouvelle is not None:
            try:
                partiel = self._texte(nouvelle)
            except ErreurPlaywright:
                pass
        return ResultatGemini(
            reponse=partiel.strip(), adresse=page.url, html=self._html(nouvelle) if nouvelle is not None else "",
            modele=self._modele, niveau=self._niveau, duree=duree, interrompue=True,
        )

    def _page(self) -> Page:
        """L'onglet piloté. Rouvert (fenêtre fermée par l'utilisateur) : ses réglages sont inconnus."""
        page = self._onglet.page()
        if page is not self._page_suivie:
            self._page_suivie, self._connus, self._chargee_a = page, False, None
        return page

    def _discussion_neuve(self, page: Page) -> None:
        """Ouvre une discussion neuve : elle affiche les réglages du compte, connus si un
        onglet les a choisis ou lus depuis le démarrage."""
        page.goto(self._url_nouvelle, wait_until="domcontentloaded")
        self._chargee_a, valeurs = self._reglages.lire()
        self._connus = valeurs is not None
        if valeurs is not None:
            self._modele, self._niveau = valeurs

    def _conversation_rouverte(self) -> None:
        """Une conversation rouverte remet le sélecteur sur SES réglages (souvent Max.)."""
        self._connus, self._chargee_a = False, None

    def _ajuster(self, page: Page, modele: str | None, niveau: str | None) -> None:
        """Règle le modèle et le niveau demandés, après avoir lu ceux de la page s'ils sont inconnus."""
        if modele is None and niveau is None:
            return
        if not self._connus:
            self._lire_reglages(page)
        self._regler(page, modele, niveau)

    def _lire_reglages(self, page: Page) -> Modes:
        lus = modes.lire_modes(page) if self._site.modes == "gemini" else modes_menu.lire_modes(page, self._site)
        self._modele, self._niveau, self._connus = lus.modele_actif, lus.niveau_actif, True
        if self._chargee_a is not None:
            self._reglages.constater(self._chargee_a, self._modele, self._niveau)
        return lus

    def _regler(self, page: Page, modele: str | None, niveau: str | None) -> None:
        changer_modele, changer_niveau = reglages_a_faire(self._modele, self._niveau, modele, niveau)
        if not (changer_modele or changer_niveau):
            return
        self._reglages.choix_en_cours()
        try:
            if changer_modele:
                if self._site.modes == "gemini":
                    modes.choisir_modele(page, modele)
                else:
                    modes_menu.choisir_modele(page, modele, self._site)
                self._modele = modele
            if changer_niveau:
                choisi = modes.choisir_niveau(page, niveau) if self._site.modes == "gemini" else False
                self._niveau = niveau if choisi else None
        except Exception:
            self._connus = False  # le clic a pu porter : relus au prochain message
            raise
        self._reglages.choisir(self._modele, self._niveau)  # la prochaine discussion neuve les reprend

    def _texte(self, reponse: Locator) -> str:
        if not self._site.texte_par_contenu:
            return reponse.inner_text()
        return reponse.evaluate(LIRE_TEXTE, {"contenu": self._site.contenu, "lignes": list(self._site.lignes_decor)})

    def _cliquer_envoyer(self, page: Page, champ: Locator, avec_pieces: bool) -> None:
        """Le bouton Envoyer (il attend la fin de l'envoi des fichiers joints) ; sans bouton
        reconnu, la touche Entrée, qui envoie sur tous ces sites."""
        try:
            bouton = attendre_repere(page, "bouton_envoyer", 5, self._r)
        except RepereIntrouvable:
            champ.first.click()
            page.keyboard.press("End")
            page.keyboard.press("Enter")
            return
        bouton.first.click(timeout=120_000 if avec_pieces else 30_000)

    def _html(self, reponse: Locator) -> str:
        s = self._site
        try:
            return reponse.evaluate(
                EXTRAIRE_HTML, {"contenu": s.contenu, "code": s.code, "entete": s.entete_code, "decor": s.decor},
            )
        except ErreurPlaywright:
            journal.warning("HTML de la réponse illisible : seul le texte est gardé", exc_info=True)
            return ""

    def _attendre_historique(self, page: Page) -> None:
        """Après ouverture d'une conversation existante, attendre que ses
        anciennes réponses soient affichées (sinon l'une d'elles serait prise
        pour la nouvelle)."""
        attendre_repere(page, "reponse", 15, self._r)
        precedent, stable_depuis = -1, time.monotonic()
        fin = time.monotonic() + 10
        while time.monotonic() < fin:
            nombre = compter(page, "reponse", self._r)
            if nombre != precedent:
                precedent, stable_depuis = nombre, time.monotonic()
            elif time.monotonic() - stable_depuis >= 1.0:
                return
            time.sleep(0.2)

    def _attendre_nouvelle_reponse(
        self, page: Page, nb_avant: int, nb_questions: int, delai: float, doit_arreter: Callable[[], bool],
    ) -> Locator:
        trouvee = attendre_nouvelle_reponse(
            compter_reponses=lambda: compter(page, "reponse", self._r),
            compter_questions=lambda: compter(page, "question", self._r),
            generation_en_cours=lambda: self._generation_en_cours(page),
            nb_reponses_avant=nb_avant,
            nb_questions_attendu=nb_questions,
            delai=delai,
            doit_arreter=doit_arreter,
        )
        if not trouvee:
            raise RepereIntrouvable("reponse")
        return premier_present(page, "reponse", self._r).nth(nb_avant)

    def _bandeau_limite(self, page: Page) -> str | None:
        """Texte du bandeau « Votre limite sera réinitialisée à … », s'il est affiché."""
        bandeau = premier_present(page, "bandeau_limite", self._r)
        if bandeau is None or not bandeau.first.is_visible():
            return None
        return " ".join(bandeau.first.inner_text().split()) or None

    def _generation_en_cours(self, page: Page) -> bool:
        bouton = premier_present(page, "bouton_arreter", self._r)
        return bouton is not None and bouton.first.is_visible()

    def _verifier_acces(self, page: Page) -> None:
        if any(m in page.url for m in self._site.verification_url) or premier_present(page, "verification", self._r):
            raise VerificationGoogle(self._site.compte)
        if self._demande_connexion(page):
            raise PasConnecteGoogle(self._site.compte)

    def _demande_connexion(self, page: Page) -> bool:
        return any(m in page.url for m in self._site.connexion_url) or premier_present(page, "lien_connexion", self._r) is not None

    def _capturer(self, page: Page) -> str | None:
        try:
            self._dossier_captures.mkdir(parents=True, exist_ok=True)
            chemin = self._dossier_captures / f"repere-{datetime.now():%Y%m%d-%H%M%S}.png"
            page.screenshot(path=str(chemin), full_page=True)
            return str(chemin)
        except ErreurPlaywright:
            journal.exception("Capture d'écran impossible")
            return None


PiloteWeb = PiloteGemini  # le même pilote, quel que soit le site
