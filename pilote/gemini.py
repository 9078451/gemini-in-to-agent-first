"""Taper un message dans Gemini, attendre la fin de la réponse et la lire."""
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote import modes
from pilote.attente import attendre_envoi, attendre_fin_reponse, attendre_nouvelle_reponse
from pilote.chrome import OngletGemini
from pilote.erreurs import (
    DelaiDepasse, ErreurPilote, Interrompu, PasConnecteGoogle, RepereIntrouvable, VerificationGoogle,
)
from pilote.modeles import Modes, ResultatGemini
from pilote.reperes import attendre_repere, compter, premier_present
from pilote.selecteurs import BLOC_CODE, CONTENU_REPONSE, DECOR_REPONSE, ENTETE_CODE, REPERES
from pilote.sonde import Sonde

journal = logging.getLogger(__name__)

# s : délai pour que la question apparaisse dans la conversation après le clic sur Envoyer.
# Large : quand le compte atteint sa limite, Gemini peut accepter le message en retard.
DELAI_ENVOI = 60.0
# Ce que la sonde lit en un seul aller-retour (voir pilote/sonde.py).
REPERES_SONDE = {
    "question": REPERES["question"],
    "reponse": REPERES["reponse"],
    "generation": REPERES["bouton_arreter"],
    "limite": REPERES["bandeau_limite"],
}
HTML_SONDE = {"contenu": CONTENU_REPONSE, "code": BLOC_CODE, "entete": ENTETE_CODE, "decor": DECOR_REPONSE}

EXTRAIRE_HTML = """(element, s) => {
  const copie = (element.querySelector(s.contenu) || element).cloneNode(true);
  copie.querySelectorAll(s.code).forEach(bloc => {
    const entete = bloc.querySelector(s.entete);
    const langue = entete ? entete.innerText.trim().split('\\n')[0].trim() : '';
    const pre = bloc.querySelector('pre');
    if (pre && langue) pre.setAttribute('data-langue', langue);
  });
  copie.querySelectorAll(s.decor).forEach(e => e.remove());
  return copie.innerHTML;
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


class PiloteGemini:
    def __init__(
        self,
        onglet: OngletGemini,
        url_nouvelle: str,
        delai_reponse: float,
        stabilite: float,
        dossier_captures: Path,
        reglages: ReglagesCompte | None = None,
    ) -> None:
        self._onglet = onglet
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

    def envoyer(
        self,
        adresse: str | None,
        texte: str,
        modele: str | None = None,
        niveau: str | None = None,
        delai: float | None = None,
        au_fil: Callable[[str, str], None] | None = None,
    ) -> ResultatGemini:
        """Envoie `texte` dans la conversation `adresse` (None = nouvelle conversation),
        après avoir réglé le modèle et le niveau demandés. `delai` remplace, pour ce
        message, la limite de temps de réponse par défaut. `au_fil(texte, html)` reçoit la
        réponse pendant qu'elle s'écrit ; s'il lève `Interrompu`, la réponse est arrêtée
        dans Gemini et l'erreur remonte avec le texte déjà écrit."""
        page = self._page()
        try:
            return self._envoyer(page, adresse, texte, modele, niveau, delai or self._delai_reponse, au_fil)
        except RepereIntrouvable as e:
            raise RepereIntrouvable(e.nom, self._capturer(page)) from e

    def preparer(self) -> None:
        """Ouvre Chrome et une nouvelle discussion Gemini, prête à recevoir un message
        (appelé au démarrage d'Agent First : le premier message n'attend plus Chrome)."""
        page = self._page()
        if not nouvelle_discussion_prete(page.url, self._url_nouvelle, compter(page, "question")):
            self._discussion_neuve(page)
        self._verifier_acces(page)
        attendre_repere(page, "champ_saisie", 30)

    def est_connecte(self) -> bool:
        return not self._demande_connexion(self._page())

    def lister_modes(self) -> Modes:
        page = self._page()
        attendre_repere(page, "bouton_mode", 15)
        return self._lire_reglages(page)

    def _envoyer(
        self, page: Page, adresse: str | None, texte: str, modele: str | None, niveau: str | None, delai: float,
        au_fil: Callable[[str, str], None] | None = None,
    ) -> ResultatGemini:
        if adresse is None:
            if not nouvelle_discussion_prete(page.url, self._url_nouvelle, compter(page, "question")):
                self._discussion_neuve(page)
        elif page.url != adresse:
            page.goto(adresse, wait_until="domcontentloaded")
            self._conversation_rouverte()
            self._attendre_historique(page)

        try:
            champ = attendre_repere(page, "champ_saisie", 15)
        except RepereIntrouvable:
            self._verifier_acces(page)
            raise
        self._verifier_acces(page)
        self._ajuster(page, modele, niveau)

        # Un seul aller-retour avec Chrome par vérification (avant : 4 à 6).
        sonde = Sonde(page, REPERES_SONDE, html=HTML_SONDE if au_fil else None)
        nb_avant = sonde.reponses()
        questions_avant = sonde.questions()
        champ.first.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        # insert_text n'appuie sur aucune touche : les retours à la ligne
        # n'envoient pas le message en morceaux.
        page.keyboard.insert_text(texte)
        attendre_repere(page, "bouton_envoyer", 5).first.click()
        try:
            attendre_envoi(sonde.questions, questions_avant, DELAI_ENVOI, sonde.limite, intervalle=0.25)
        except ErreurPilote:
            # Vider le champ : sinon Gemini peut envoyer ce message plus tard, tout seul,
            # alors qu'Agent First a déjà abandonné.
            champ.first.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            raise

        # Un seul délai pour tout le message : Gemini peut réfléchir longtemps
        # avant même d'afficher le début de sa réponse.
        debut = time.monotonic()
        fin = debut + delai
        sonde.viser(nb_avant)
        suivi = (lambda texte: au_fil(texte, sonde.html())) if au_fil else None
        try:
            trouvee = attendre_nouvelle_reponse(
                compter_reponses=sonde.reponses,
                compter_questions=sonde.questions,
                generation_en_cours=sonde.generation,
                nb_reponses_avant=nb_avant,
                nb_questions_attendu=questions_avant + 1,
                delai=delai,
                intervalle=0.2,
                au_fil=suivi,
            )
            if not trouvee:
                raise RepereIntrouvable("reponse")
            reponse = attendre_fin_reponse(
                lire_texte=sonde.texte,
                generation_en_cours=sonde.generation,
                delai_max=max(0.0, fin - time.monotonic()),
                stabilite=self._stabilite,
                intervalle=0.25,
                au_fil=suivi,
            )
        except Interrompu:
            self._arreter_generation(page)
            raise Interrompu(sonde.texte().strip(), sonde.html(), page.url)
        except DelaiDepasse as e:
            raise DelaiDepasse(delai, e.partiel) from e  # le message cite la limite entière, pas le reste
        nouvelle = premier_present(page, "reponse").nth(nb_avant)
        return ResultatGemini(
            reponse=reponse.strip(),
            adresse=page.url,
            html=self._html(nouvelle),
            modele=self._modele,
            niveau=self._niveau,
            duree=round(time.monotonic() - debut, 1),
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
        lus = modes.lire_modes(page)
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
                modes.choisir_modele(page, modele)
                self._modele = modele
            if changer_niveau:
                self._niveau = niveau if modes.choisir_niveau(page, niveau) else None
        except Exception:
            self._connus = False  # le clic a pu porter : relus au prochain message
            raise
        self._reglages.choisir(self._modele, self._niveau)  # la prochaine discussion neuve les reprend

    def _html(self, reponse: Locator) -> str:
        try:
            return reponse.evaluate(
                EXTRAIRE_HTML,
                {"contenu": CONTENU_REPONSE, "code": BLOC_CODE, "entete": ENTETE_CODE, "decor": DECOR_REPONSE},
            )
        except ErreurPlaywright:
            journal.warning("HTML de la réponse illisible : seul le texte est gardé", exc_info=True)
            return ""

    def _attendre_historique(self, page: Page) -> None:
        """Après ouverture d'une conversation existante, attendre que ses
        anciennes réponses soient affichées (sinon l'une d'elles serait prise
        pour la nouvelle)."""
        attendre_repere(page, "reponse", 15)
        precedent, stable_depuis = -1, time.monotonic()
        fin = time.monotonic() + 10
        while time.monotonic() < fin:
            nombre = compter(page, "reponse")
            if nombre != precedent:
                precedent, stable_depuis = nombre, time.monotonic()
            elif time.monotonic() - stable_depuis >= 1.0:
                return
            time.sleep(0.2)

    def _arreter_generation(self, page: Page) -> None:
        """Clique sur « Interrompre la réponse » (arrêt demandé par l'utilisateur)."""
        try:
            bouton = premier_present(page, "bouton_arreter")
            if bouton is not None and bouton.first.is_visible():
                bouton.first.click(timeout=3000)
        except ErreurPlaywright:
            journal.warning("Bouton « Interrompre » introuvable : Gemini finira sa réponse seul", exc_info=True)

    def _verifier_acces(self, page: Page) -> None:
        if "/sorry/" in page.url or "challenge" in page.url:
            raise VerificationGoogle()
        if self._demande_connexion(page):
            raise PasConnecteGoogle()

    def _demande_connexion(self, page: Page) -> bool:
        return "accounts.google.com" in page.url or premier_present(page, "lien_connexion") is not None

    def _capturer(self, page: Page) -> str | None:
        try:
            self._dossier_captures.mkdir(parents=True, exist_ok=True)
            chemin = self._dossier_captures / f"repere-{datetime.now():%Y%m%d-%H%M%S}.png"
            page.screenshot(path=str(chemin), full_page=True)
            return str(chemin)
        except ErreurPlaywright:
            journal.exception("Capture d'écran impossible")
            return None
