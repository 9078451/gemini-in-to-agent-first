# agent.first v2 — Plan A : pilote (modèle, niveau, HTML), historique et API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** le pilote choisit le modèle et le niveau de réflexion de Gemini et
lit les réponses en HTML ; Agent First garde un historique SQLite et expose
l'API `/api/...` dont l'app web (plan B) aura besoin.

**Architecture :** `pilote/modes.py` lit et règle le sélecteur de mode de
Gemini ; `PiloteGemini.envoyer` l'appelle avant de taper et renvoie aussi le
HTML de la réponse. `agent_first/nettoyage.py` (nh3) nettoie ce HTML,
`agent_first/historique.py` stocke conversations et messages dans SQLite,
`agent_first/serveur.py` est réécrit autour de l'historique. La fenêtre
CustomTkinter de la v1 est retirée (l'app web arrive au plan B).

**Tech Stack :** Python 3.13, Playwright (sync, CDP), FastAPI, sqlite3 (stdlib), nh3, pytest.

**Spec :** `docs/superpowers/specs/2026-10-15-gemini-agent-first-v2-design.md`

## Global Constraints

- Tout ce qui a été établi en v1 reste vrai (Windows 11, Python 3.13, Chrome dédié `profil-chrome-gemini/` sur le port 9222, Agent First sur `127.0.0.1:8765`, délai réponse 180 s, stabilité 2 s, délai serveur 290 s, Playwright utilisé uniquement depuis le fil `file-gemini`).
- Tous les repères de la page Gemini sont dans `pilote/selecteurs.py`.
- Le module de lecture/réglage du sélecteur s'appelle `pilote/modes.py` (et non `pilote/modeles.py` comme écrit dans la fiche : ce nom contient déjà les types de données) ; ses types `Option` et `Modes` vont dans `pilote/modeles.py`.
- Modèles relevés le 2026-10-15 : `3.5 Flash-Lite`, `3.8 Flash`, `3.1 Pro`, `4 Argon` ; niveaux `Min.`, `Moyen`, `Max.` ; entrée de sous-menu `Niveau de réflexion`. Le bouton du sélecteur affiche « …, actuellement <nom sans numéro> ».
- Réglages de l'utilisateur à remettre après les essais réels : **4 Argon** + **Min.**
- Historique : `donnees/historique.db` (exclu de git via `donnees/`).
- Textes visibles par l'utilisateur en français. Chaque commit se termine par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` et est suivi de `git push` (branche `main`).

## Review Focus

1. **Modèle déjà actif dans Gemini** (choisi à la main dans le Chrome dédié) : pas d'erreur ni de manipulation inutile → `lister_modes` met à jour la mémoire du pilote ; vérification réelle tâche 2 étape 5.
2. **Changement de modèle au milieu d'une conversation** (reprise d'une ancienne avec un autre modèle) : le nouveau modèle est appliqué avant de taper dans cette conversation → vérification réelle tâche 2 étape 5.
3. **Réponse avec des éléments inconnus** (image, balise maison de Gemini) : le texte est gardé, les balises inconnues retirées → `test_balises_inconnues_retirees_texte_garde` (tâche 3).
4. **Conversation supprimée pendant un envoi** : la réponse est renvoyée mais pas enregistrée, sans erreur 500 → `test_suppression_pendant_envoi` (tâche 5).
5. **Recherche avec `%` ou `_`** : pas de faux résultats (pas de jokers SQL) → `test_recherche_sans_jokers` (tâche 4).

---

### Task 1 : Lecture et réglage du sélecteur de mode

**Files :**
- Create : `pilote/reperes.py`, `pilote/modes.py`
- Modify : `pilote/gemini.py` (les fonctions de repérage déménagent dans `pilote/reperes.py`), `pilote/selecteurs.py`, `pilote/erreurs.py`, `pilote/modeles.py`
- Test : `tests/test_modes.py`

**Interfaces :**
- Produces :
  - `pilote.reperes` : `premier_present(page, nom) -> Locator | None`, `attendre_repere(page, nom, delai) -> Locator`, `compter(page, nom) -> int`
  - `pilote.modeles` : `Option(nom: str, description: str, actif: bool = False)`, `Modes(modeles: list[Option], niveaux: list[Option])` avec propriétés `modele_actif`, `niveau_actif`
  - `pilote.erreurs` : `ModeleIntrouvable(nom)`, `NiveauIntrouvable(nom)`
  - `pilote.modes` : `nom_court(modele: str) -> str`, `lire_modes(page) -> Modes`, `choisir_modele(page, nom) -> None`, `choisir_niveau(page, nom) -> bool` (False si Gemini ne propose pas de niveau) ; script `python -m pilote.modes [--modele M] [--niveau N]`
  - `pilote.selecteurs` : `REPERES["bouton_mode"]`, `OPTION_MENU`, `OPTION_MODELE`, `LIBELLE_OPTION`, `SOUS_LIBELLE_OPTION`, `ENTREE_NIVEAU`

- [ ] **Step 1 : Écrire les tests (ils échouent)**

`tests/test_modes.py` :
```python
from pilote.modeles import Modes, Option
from pilote.modes import nom_court


def test_nom_court_retire_le_numero():
    assert nom_court("4 Argon") == "Argon"
    assert nom_court("3.5 Flash-Lite") == "Flash-Lite"


def test_nom_court_sans_numero_inchange():
    assert nom_court("Argon") == "Argon"


def test_nom_court_garde_les_noms_composes():
    assert nom_court("3.1 Pro Max") == "Pro Max"


def test_modes_actifs():
    modes = Modes(
        [Option("3.1 Pro", "Raisonnement avancé"), Option("4 Argon", "Tâches complexes", True)],
        [Option("Min.", "Rapide et efficace", True), Option("Max.", "Très poussé")],
    )
    assert (modes.modele_actif, modes.niveau_actif) == ("4 Argon", "Min.")
    assert Modes([], []).modele_actif is None
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_modes.py -v`
Expected : FAIL — `ImportError: cannot import name 'Modes' from 'pilote.modeles'`

- [ ] **Step 3 : Types, erreurs et repères**

Ajouter à `pilote/modeles.py` (après `ResultatGemini`, avant `Pilote`) :
```python
@dataclass(frozen=True)
class Option:
    nom: str
    description: str
    actif: bool = False


@dataclass(frozen=True)
class Modes:
    modeles: list[Option]
    niveaux: list[Option]

    @property
    def modele_actif(self) -> str | None:
        return next((o.nom for o in self.modeles if o.actif), None)

    @property
    def niveau_actif(self) -> str | None:
        return next((o.nom for o in self.niveaux if o.actif), None)
```

Ajouter à `pilote/erreurs.py` :
```python
class ModeleIntrouvable(ErreurPilote):
    def __init__(self, nom: str) -> None:
        self.nom = nom
        super().__init__(f"Le modèle « {nom} » n'est pas proposé par Gemini.")


class NiveauIntrouvable(ErreurPilote):
    def __init__(self, nom: str) -> None:
        self.nom = nom
        super().__init__(f"Le niveau de réflexion « {nom} » n'est pas proposé par Gemini.")
```

Dans `pilote/selecteurs.py`, ajouter l'entrée `"bouton_mode"` au dictionnaire `REPERES` et les constantes à la fin du fichier :
```python
    "bouton_mode": [
        "button[aria-label*='sélecteur de mode']",
        "button[aria-label*='mode picker']",
    ],
```
```python

# Sélecteur de mode : menu des modèles et sous-menu « Niveau de réflexion ».
OPTION_MENU = "gem-menu-item[role='menuitem']"
OPTION_MODELE = "gem-menu-item[data-mode-id]"
LIBELLE_OPTION = ".label"
SOUS_LIBELLE_OPTION = ".sublabel"
ENTREE_NIVEAU = "Niveau de réflexion"
```

Créer `pilote/reperes.py` en y déplaçant **telles quelles** les trois fonctions `premier_present`, `attendre_repere` et `compter` de `pilote/gemini.py` :
```python
"""Trouver les repères de la page Gemini (candidats de `selecteurs.REPERES`)."""
import time

from playwright.sync_api import Locator, Page

from pilote.erreurs import RepereIntrouvable
from pilote.selecteurs import REPERES


def premier_present(page: Page, nom: str) -> Locator | None:
    """Premier candidat du repère `nom` qui trouve au moins un élément."""
    for selecteur in REPERES[nom]:
        elements = page.locator(selecteur)
        if elements.count() > 0:
            return elements
    return None


def attendre_repere(page: Page, nom: str, delai: float) -> Locator:
    fin = time.monotonic() + delai
    while True:
        elements = premier_present(page, nom)
        if elements is not None:
            return elements
        if time.monotonic() >= fin:
            raise RepereIntrouvable(nom)
        time.sleep(0.3)


def compter(page: Page, nom: str) -> int:
    elements = premier_present(page, nom)
    return elements.count() if elements is not None else 0
```
Dans `pilote/gemini.py` : supprimer ces trois fonctions et l'import `REPERES`, ajouter `from pilote.reperes import attendre_repere, compter, premier_present`.

- [ ] **Step 4 : Écrire `pilote/modes.py`**

```python
"""Lire et régler le sélecteur de mode de Gemini : modèle et niveau de réflexion.

Usage :
  python -m pilote.modes                                  affiche modèles et niveaux
  python -m pilote.modes --modele "3.1 Pro" --niveau Max.  règle puis affiche
"""
import argparse
import re
import sys
import time

from playwright.sync_api import Locator, Page

from pilote.erreurs import ErreurPilote, ModeleIntrouvable, NiveauIntrouvable
from pilote.modeles import Modes, Option
from pilote.reperes import attendre_repere
from pilote.selecteurs import ENTREE_NIVEAU, LIBELLE_OPTION, OPTION_MENU, OPTION_MODELE, SOUS_LIBELLE_OPTION

LIRE_OPTIONS = """(elements, s) => elements.filter(e => e.offsetParent).map(e => ({
  nom: (e.querySelector(s.libelle) || e).innerText.trim(),
  description: (e.querySelector(s.sous_libelle) || {innerText: ''}).innerText.trim(),
  actif: e.classList.contains('selected'),
  modele: e.matches(s.modele),
}))"""
OPTION_NIVEAU = f"{OPTION_MENU}:not({OPTION_MODELE})"


def nom_court(modele: str) -> str:
    """« 4 Argon » -> « Argon » : ce qu'affiche le bouton du sélecteur."""
    morceaux = modele.split(maxsplit=1)
    if len(morceaux) == 2 and re.fullmatch(r"[\d.]+", morceaux[0]):
        return morceaux[1]
    return modele


def lire_modes(page: Page) -> Modes:
    """Ouvre le sélecteur, lit modèles et niveaux, referme sans rien changer."""
    _ouvrir(page)
    try:
        modeles = [Option(o["nom"], o["description"], o["actif"]) for o in _lire(page) if o["modele"]]
        niveaux = []
        if _ouvrir_niveaux(page):
            niveaux = [
                Option(o["nom"], o["description"], o["actif"])
                for o in _lire(page)
                if not o["modele"] and o["nom"] != ENTREE_NIVEAU
            ]
    finally:
        _fermer(page)
    return Modes(modeles, niveaux)


def choisir_modele(page: Page, nom: str) -> None:
    _ouvrir(page)
    try:
        option = _option(page, nom, OPTION_MODELE)
        if option.count() == 0:
            raise ModeleIntrouvable(nom)
        option.first.click()
    finally:
        _fermer(page)
    bouton = attendre_repere(page, "bouton_mode", 5).first
    fin = time.monotonic() + 5
    while not (bouton.get_attribute("aria-label") or "").endswith(nom_court(nom)):
        if time.monotonic() >= fin:
            raise ModeleIntrouvable(nom)
        time.sleep(0.2)


def choisir_niveau(page: Page, nom: str) -> bool:
    """Règle le niveau de réflexion. False si Gemini ne propose pas de niveau."""
    _ouvrir(page)
    try:
        if not _ouvrir_niveaux(page):
            return False
        option = _option(page, nom, OPTION_NIVEAU)
        if option.count() == 0:
            raise NiveauIntrouvable(nom)
        option.first.click()
    finally:
        _fermer(page)
    if lire_modes(page).niveau_actif != nom:
        raise NiveauIntrouvable(nom)
    return True


def _ouvrir(page: Page) -> None:
    attendre_repere(page, "bouton_mode", 10).first.click()
    page.locator(OPTION_MODELE).first.wait_for(state="visible", timeout=5000)


def _fermer(page: Page) -> None:
    for _ in range(2):
        page.keyboard.press("Escape")
        time.sleep(0.3)


def _lire(page: Page) -> list[dict]:
    return page.locator(OPTION_MENU).evaluate_all(
        LIRE_OPTIONS, {"libelle": LIBELLE_OPTION, "sous_libelle": SOUS_LIBELLE_OPTION, "modele": OPTION_MODELE}
    )


def _option(page: Page, nom: str, selecteur: str) -> Locator:
    libelle = page.locator(LIBELLE_OPTION, has_text=re.compile(rf"^\s*{re.escape(nom)}\s*$"))
    return page.locator(selecteur).filter(has=libelle).filter(visible=True)


def _ouvrir_niveaux(page: Page) -> bool:
    entree = _option(page, ENTREE_NIVEAU, OPTION_MENU)
    if entree.count() == 0:
        return False
    entree.first.click()
    fin = time.monotonic() + 5
    while time.monotonic() < fin:
        if any(not o["modele"] and o["nom"] != ENTREE_NIVEAU for o in _lire(page)):
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    import config
    from pilote.chrome import ChromeDedie

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Lit ou règle le modèle et le niveau de réflexion de Gemini.")
    parser.add_argument("--modele")
    parser.add_argument("--niveau")
    args = parser.parse_args()

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    try:
        page = chrome.page()
        attendre_repere(page, "bouton_mode", 15)
        if args.modele:
            choisir_modele(page, args.modele)
        if args.niveau:
            choisir_niveau(page, args.niveau)
        modes = lire_modes(page)
    except ErreurPilote as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        return 1
    finally:
        chrome.fermer()
    for titre, options in (("Modèles", modes.modeles), ("Niveaux de réflexion", modes.niveaux)):
        print(titre)
        for o in options:
            print(f"  {'✓' if o.actif else ' '} {o.nom:16} {o.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5 : Vérifier que les tests passent**

Run : `.venv\Scripts\python -m pytest -v`
Expected : 42 passed (38 + 4)

- [ ] **Step 6 : Vérifications réelles (Chrome dédié connecté)**

1. `.venv\Scripts\python -m pilote.modes` → 4 modèles avec leur description, ✓ devant « 4 Argon » ; 3 niveaux, ✓ devant « Min. ».
2. `.venv\Scripts\python -m pilote.modes --modele "3.1 Pro" --niveau "Max."` → ✓ devant « 3.1 Pro » et « Max. ».
3. `.venv\Scripts\python -m pilote.modes --modele "9 Zeta"` → `ERREUR : Le modèle « 9 Zeta » n'est pas proposé par Gemini.`
4. Remettre : `.venv\Scripts\python -m pilote.modes --modele "4 Argon" --niveau "Min."` → ✓ « 4 Argon » et « Min. ».
5. `.venv\Scripts\python -m pilote.inspecter` → `bouton_mode` trouvé (1).

- [ ] **Step 7 : Commit**

```bash
git add pilote/reperes.py pilote/modes.py pilote/gemini.py pilote/selecteurs.py pilote/erreurs.py pilote/modeles.py tests/test_modes.py
git commit -m "feat: lecture et réglage du modèle et du niveau de réflexion de Gemini"
git push
```

---

### Task 2 : Envoi avec modèle et niveau, réponse en HTML et durée

**Files :**
- Modify : `pilote/gemini.py`, `pilote/modeles.py`, `pilote/selecteurs.py`, `pilote/essai.py`
- Test : `tests/test_reglages.py`

**Interfaces :**
- Consumes : `pilote.modes` (`lire_modes`, `choisir_modele`, `choisir_niveau`), `pilote.reperes`
- Produces :
  - `ResultatGemini(reponse, adresse, html="", modele=None, niveau=None, duree=0.0)`
  - protocole `Pilote` : `envoyer(adresse, texte, modele=None, niveau=None) -> ResultatGemini`, `est_connecte() -> bool`, `lister_modes() -> Modes`
  - `pilote.gemini.reglages_a_faire(dernier_modele, dernier_niveau, modele, niveau) -> tuple[bool, bool]`
  - `PiloteGemini.envoyer(adresse, texte, modele=None, niveau=None)`, `PiloteGemini.lister_modes()`
  - `pilote.selecteurs` : `CONTENU_REPONSE`, `BLOC_CODE`, `ENTETE_CODE`, `DECOR_REPONSE`

- [ ] **Step 1 : Écrire les tests (ils échouent)**

`tests/test_reglages.py` :
```python
from pilote.gemini import reglages_a_faire


def test_premier_message_regle_tout():
    assert reglages_a_faire(None, None, "3.1 Pro", "Max.") == (True, True)


def test_rien_a_changer():
    assert reglages_a_faire("3.1 Pro", "Max.", "3.1 Pro", "Max.") == (False, False)


def test_niveau_seul():
    assert reglages_a_faire("3.1 Pro", "Min.", "3.1 Pro", "Max.") == (False, True)


def test_changer_de_modele_reapplique_le_niveau():
    assert reglages_a_faire("4 Argon", "Max.", "3.1 Pro", "Max.") == (True, True)


def test_rien_demande():
    assert reglages_a_faire("4 Argon", "Min.", None, None) == (False, False)
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_reglages.py -v`
Expected : FAIL — `ImportError: cannot import name 'reglages_a_faire'`

- [ ] **Step 3 : Types et repères**

Dans `pilote/modeles.py`, remplacer `ResultatGemini` et `Pilote` par :
```python
@dataclass(frozen=True)
class ResultatGemini:
    reponse: str
    adresse: str  # adresse de la conversation, ex. https://gemini.google.com/app/abc123
    html: str = ""
    modele: str | None = None
    niveau: str | None = None
    duree: float = 0.0  # secondes entre l'envoi et la fin de la réponse
```
```python
class Pilote(Protocol):
    def envoyer(
        self, adresse: str | None, texte: str, modele: str | None = None, niveau: str | None = None
    ) -> ResultatGemini: ...

    def est_connecte(self) -> bool: ...

    def lister_modes(self) -> Modes: ...
```
(`Pilote` est placé après `Modes` dans le fichier.)

Ajouter à la fin de `pilote/selecteurs.py` :
```python

# Réponse en HTML : contenu utile, blocs de code et décor de Gemini à retirer.
CONTENU_REPONSE = ".markdown"
BLOC_CODE = "code-block"
ENTETE_CODE = ".code-block-decoration"
DECOR_REPONSE = "button, gem-icon-button, gem-icon, mat-icon, gem-popover, .table-footer, .code-block-decoration"
```

- [ ] **Step 4 : Réécrire `pilote/gemini.py`**

```python
"""Taper un message dans Gemini, attendre la fin de la réponse et la lire."""
import logging
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote import modes
from pilote.attente import attendre_fin_reponse
from pilote.chrome import ChromeDedie
from pilote.erreurs import DelaiDepasse, PasConnecteGoogle, RepereIntrouvable, VerificationGoogle
from pilote.modeles import Modes, ResultatGemini
from pilote.reperes import attendre_repere, compter, premier_present
from pilote.selecteurs import BLOC_CODE, CONTENU_REPONSE, DECOR_REPONSE, ENTETE_CODE

journal = logging.getLogger(__name__)

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


class PiloteGemini:
    def __init__(
        self,
        chrome: ChromeDedie,
        url_nouvelle: str,
        delai_reponse: float,
        stabilite: float,
        dossier_captures: Path,
    ) -> None:
        self._chrome = chrome
        self._url_nouvelle = url_nouvelle
        self._delai_reponse = delai_reponse
        self._stabilite = stabilite
        self._dossier_captures = dossier_captures
        # Derniers réglages connus du sélecteur de Gemini.
        self._modele: str | None = None
        self._niveau: str | None = None

    def envoyer(
        self, adresse: str | None, texte: str, modele: str | None = None, niveau: str | None = None
    ) -> ResultatGemini:
        """Envoie `texte` dans la conversation `adresse` (None = nouvelle conversation),
        après avoir réglé le modèle et le niveau demandés."""
        page = self._chrome.page()
        try:
            return self._envoyer(page, adresse, texte, modele, niveau)
        except RepereIntrouvable as e:
            raise RepereIntrouvable(e.nom, self._capturer(page)) from e

    def est_connecte(self) -> bool:
        return not self._demande_connexion(self._chrome.page())

    def lister_modes(self) -> Modes:
        page = self._chrome.page()
        attendre_repere(page, "bouton_mode", 15)
        lus = modes.lire_modes(page)
        self._modele, self._niveau = lus.modele_actif, lus.niveau_actif
        return lus

    def _envoyer(
        self, page: Page, adresse: str | None, texte: str, modele: str | None, niveau: str | None
    ) -> ResultatGemini:
        if adresse is None:
            page.goto(self._url_nouvelle, wait_until="domcontentloaded")
        elif page.url != adresse:
            page.goto(adresse, wait_until="domcontentloaded")
            self._attendre_historique(page)

        try:
            champ = attendre_repere(page, "champ_saisie", 15)
        except RepereIntrouvable:
            self._verifier_acces(page)
            raise
        self._verifier_acces(page)
        self._regler(page, modele, niveau)

        nb_avant = compter(page, "reponse")
        champ.first.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        # insert_text n'appuie sur aucune touche : les retours à la ligne
        # n'envoient pas le message en morceaux.
        page.keyboard.insert_text(texte)
        attendre_repere(page, "bouton_envoyer", 5).first.click()

        # Un seul délai pour tout le message : Gemini peut réfléchir longtemps
        # avant même d'afficher le début de sa réponse.
        debut = time.monotonic()
        fin = debut + self._delai_reponse
        nouvelle = self._attendre_nouvelle_reponse(page, nb_avant, fin)
        reponse = attendre_fin_reponse(
            lire_texte=nouvelle.inner_text,
            generation_en_cours=lambda: self._generation_en_cours(page),
            delai_max=max(0.0, fin - time.monotonic()),
            stabilite=self._stabilite,
        )
        return ResultatGemini(
            reponse=reponse.strip(),
            adresse=page.url,
            html=self._html(nouvelle),
            modele=self._modele,
            niveau=self._niveau,
            duree=round(time.monotonic() - debut, 1),
        )

    def _regler(self, page: Page, modele: str | None, niveau: str | None) -> None:
        changer_modele, changer_niveau = reglages_a_faire(self._modele, self._niveau, modele, niveau)
        if changer_modele:
            modes.choisir_modele(page, modele)
            self._modele = modele
        if changer_niveau:
            self._niveau = niveau if modes.choisir_niveau(page, niveau) else None

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

    def _attendre_nouvelle_reponse(self, page: Page, nb_avant: int, fin: float) -> Locator:
        while time.monotonic() < fin:
            reponses = premier_present(page, "reponse")
            if reponses is not None and reponses.count() > nb_avant:
                return reponses.nth(nb_avant)
            time.sleep(0.3)
        if self._generation_en_cours(page):
            raise DelaiDepasse(self._delai_reponse, "")
        raise RepereIntrouvable("reponse")

    def _generation_en_cours(self, page: Page) -> bool:
        bouton = premier_present(page, "bouton_arreter")
        return bouton is not None and bouton.first.is_visible()

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
```

- [ ] **Step 5 : Options de `pilote/essai.py`**

Remplacer le corps de `main()` à partir de `parser.add_argument("--suite", ...)` par :
```python
    parser.add_argument("--suite", metavar="URL", help="adresse d'une conversation Gemini à continuer")
    parser.add_argument("--modele", help="ex. « 3.1 Pro »")
    parser.add_argument("--niveau", help="Min., Moyen ou Max.")
    parser.add_argument("--html", action="store_true", help="affiche aussi le HTML de la réponse")
    args = parser.parse_args()

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    pilote = PiloteGemini(
        chrome, config.URL_GEMINI, config.DELAI_REPONSE, config.STABILITE, config.DOSSIER_JOURNAUX
    )
    try:
        resultat = pilote.envoyer(args.suite, args.texte.replace("\\n", "\n"), args.modele, args.niveau)
    except ErreurPilote as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        return 1
    finally:
        chrome.fermer()
    print(resultat.reponse)
    if args.html:
        print("\n--- HTML ---\n" + resultat.html)
    print(
        f"\n[conversation : {resultat.adresse} · modèle : {resultat.modele or '?'}"
        f" · niveau : {resultat.niveau or '?'} · {resultat.duree} s]"
    )
    return 0
```
et ajouter à la docstring du module : `python -m pilote.essai "Bonjour" --modele "3.1 Pro" --niveau Max. --html`.

- [ ] **Step 6 : Tests**

Run : `.venv\Scripts\python -m pytest -v`
Expected : 47 passed

- [ ] **Step 7 : Vérifications réelles**

1. `.venv\Scripts\python -m pilote.essai "Réponds juste : ok" --modele "3.1 Pro" --niveau "Max."` → réponse, puis `[… modèle : 3.1 Pro · niveau : Max. · N s]` ; `python -m pilote.modes` → ✓ « 3.1 Pro » et ✓ « Max. ».
2. Même commande une 2ᵉ fois → pas de manipulation du sélecteur visible dans le Chrome dédié (réglages déjà faits).
3. `.venv\Scripts\python -m pilote.essai "Réponds en français, très court : un titre, une liste à puces de 2 éléments avec un mot en gras, un tableau de 2 lignes, et un exemple de code Python de 2 lignes." --modele "3.8 Flash" --html` → le HTML contient `<h2`, `<li>`, `<b>`, `<table>`, `<pre data-langue="Python">`, et **ne contient pas** `<button`, `mat-icon`, `code-block-decoration`.
4. `--suite <URL de l'étape 3>` avec `--modele "4 Argon"` → la réponse arrive dans la même conversation, modèle « 4 Argon » (Review Focus 2).
5. Choisir « 3.1 Pro » à la main dans le Chrome dédié, puis `python -m pilote.modes` → ✓ « 3.1 Pro » (Review Focus 1, lecture fidèle).
6. Remettre : `.venv\Scripts\python -m pilote.modes --modele "4 Argon" --niveau "Min."`.

- [ ] **Step 8 : Commit**

```bash
git add pilote/gemini.py pilote/modeles.py pilote/selecteurs.py pilote/essai.py tests/test_reglages.py
git commit -m "feat: envoi avec modèle et niveau, réponse en HTML et durée"
git push
```

---

### Task 3 : Nettoyage du HTML des réponses

**Files :**
- Create : `agent_first/nettoyage.py`
- Modify : `requirements.txt` (ajout de `nh3>=0.2.17`)
- Test : `tests/test_nettoyage.py`

**Interfaces :**
- Produces : `agent_first.nettoyage.nettoyer_html(html: str) -> str`

- [ ] **Step 1 : Installer nh3**

Ajouter la ligne `nh3>=0.2.17` à `requirements.txt`, puis Run : `.venv\Scripts\python -m pip install -r requirements.txt`
Expected : nh3 installé.

- [ ] **Step 2 : Écrire les tests (ils échouent)**

`tests/test_nettoyage.py` :
```python
from agent_first.nettoyage import nettoyer_html


def test_garde_la_mise_en_forme():
    html = (
        '<div class="markdown"><h2>Titre</h2><ul><li><b>gras</b> texte</li></ul>'
        "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table></div>"
    )
    assert nettoyer_html(html) == (
        "<h2>Titre</h2><ul><li><b>gras</b> texte</li></ul>"
        "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>"
    )


def test_garde_la_langue_du_code_sans_les_couleurs():
    html = '<pre data-langue="Python"><code class="code-container"><span class="hljs-string">x = 1</span></code></pre>'
    assert nettoyer_html(html) == '<pre data-langue="Python"><code>x = 1</code></pre>'


def test_retire_les_scripts():
    assert nettoyer_html("<p>a</p><script>alert(1)</script>") == "<p>a</p>"


def test_retire_les_attributs_dangereux():
    assert nettoyer_html('<p onclick="x()" style="color:red">a</p>') == "<p>a</p>"


def test_liens_ouverts_a_part():
    propre = nettoyer_html('<a href="https://exemple.fr">x</a>')
    assert 'href="https://exemple.fr"' in propre
    assert 'target="_blank"' in propre
    assert 'rel="noopener noreferrer"' in propre


def test_lien_javascript_neutralise():
    assert "javascript" not in nettoyer_html('<a href="javascript:alert(1)">x</a>')


def test_balises_inconnues_retirees_texte_garde():
    html = '<response-element><table-block><p>Texte</p></table-block></response-element><img src="x.png">'
    assert nettoyer_html(html) == "<p>Texte</p>"
```

- [ ] **Step 3 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_nettoyage.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'agent_first.nettoyage'`

- [ ] **Step 4 : Écrire `agent_first/nettoyage.py`**

```python
"""Nettoyer le HTML des réponses Gemini : seules les balises de mise en forme restent."""
import nh3

BALISES = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s", "del",
    "sup", "sub", "code", "pre", "blockquote", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td", "a",
}
ATTRIBUTS = {"a": {"href"}, "pre": {"data-langue"}, "ol": {"start"}, "th": {"align"}, "td": {"align"}}


def nettoyer_html(html: str) -> str:
    return nh3.clean(
        html,
        tags=BALISES,
        attributes=ATTRIBUTS,
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"a": {"target": "_blank"}},
    )
```

- [ ] **Step 5 : Vérifier qu'ils passent**

Run : `.venv\Scripts\python -m pytest -v`
Expected : 54 passed

- [ ] **Step 6 : Commit**

```bash
git add requirements.txt agent_first/nettoyage.py tests/test_nettoyage.py
git commit -m "feat: nettoyage du HTML des réponses Gemini"
git push
```

---

### Task 4 : Historique SQLite

**Files :**
- Create : `agent_first/historique.py`
- Test : `tests/test_historique.py`

**Interfaces :**
- Produces : `agent_first.historique` :
  - `ConversationInconnue(KeyError)`, `titre_depuis(texte) -> str` (une ligne, 60 caractères max.)
  - `Conversation(id, titre, adresse, modele, niveau, cree_le, modifie_le, nb_messages)`
  - `Message(id, conversation_id, role, texte, html, modele, niveau, duree, cree_le)` — `role` ∈ `toi`, `gemini`, `erreur`
  - `Historique(fichier: Path, maintenant=datetime.now)` avec `creer(modele=None, niveau=None) -> Conversation`, `conversation(id) -> Conversation`, `lister(recherche="", periode="tout") -> list[Conversation]` (sans les conversations vides, la plus récente d'abord), `messages(id) -> list[Message]`, `ajouter_message(id, role, texte, html=None, modele=None, niveau=None, duree=None) -> Message`, `enregistrer_adresse(id, adresse)`, `supprimer(id)`, `statistiques(periode="7j") -> dict` (`conversations`, `messages`, `modele_favori`, `temps_moyen`)
  - périodes : `"7j"`, `"30j"`, `"tout"` ; dates au format ISO à la seconde

- [ ] **Step 1 : Écrire les tests (ils échouent)**

`tests/test_historique.py` :
```python
from datetime import datetime, timedelta

import pytest

from agent_first.historique import ConversationInconnue, Historique, titre_depuis


class Horloge:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 15, 12, 0, 0)

    def __call__(self) -> datetime:
        return self.t

    def avancer(self, **duree) -> None:
        self.t += timedelta(**duree)


@pytest.fixture
def horloge():
    return Horloge()


@pytest.fixture
def historique(tmp_path, horloge):
    return Historique(tmp_path / "historique.db", horloge)


def test_titre_depuis_premier_message(historique):
    c = historique.creer("3.1 Pro", "Max.")
    historique.ajouter_message(c.id, "toi", "Écris un texte\nsur les phares")
    historique.ajouter_message(c.id, "toi", "Autre chose")
    assert historique.conversation(c.id).titre == "Écris un texte sur les phares"


def test_titre_long_coupe():
    titre = titre_depuis("mot " * 40)
    assert len(titre) == 60
    assert titre.endswith("…")


def test_messages_dans_l_ordre(historique):
    c = historique.creer()
    historique.ajouter_message(c.id, "toi", "Bonjour", modele="4 Argon", niveau="Min.")
    historique.ajouter_message(c.id, "gemini", "Salut", html="<p>Salut</p>", modele="4 Argon", niveau="Min.", duree=3.2)
    messages = historique.messages(c.id)
    assert [(m.role, m.texte) for m in messages] == [("toi", "Bonjour"), ("gemini", "Salut")]
    assert (messages[1].html, messages[1].duree) == ("<p>Salut</p>", 3.2)
    assert (historique.conversation(c.id).modele, historique.conversation(c.id).niveau) == ("4 Argon", "Min.")


def test_garde_tout_apres_redemarrage(tmp_path, horloge):
    fichier = tmp_path / "donnees" / "historique.db"
    h = Historique(fichier, horloge)
    c = h.creer()
    h.ajouter_message(c.id, "toi", "Bonjour")
    h.enregistrer_adresse(c.id, "https://gemini.google.com/app/abc")
    relu = Historique(fichier, horloge)
    assert relu.conversation(c.id).adresse == "https://gemini.google.com/app/abc"
    assert [m.texte for m in relu.messages(c.id)] == ["Bonjour"]


def test_liste_recente_d_abord_sans_conversations_vides(historique, horloge):
    a = historique.creer()
    historique.ajouter_message(a.id, "toi", "Premier")
    horloge.avancer(minutes=5)
    b = historique.creer()
    historique.ajouter_message(b.id, "toi", "Second")
    historique.creer()
    conversations = historique.lister()
    assert [c.titre for c in conversations] == ["Second", "Premier"]
    assert conversations[0].nb_messages == 1


def test_recherche_dans_titres_et_messages(historique):
    a = historique.creer()
    historique.ajouter_message(a.id, "toi", "Les phares")
    b = historique.creer()
    historique.ajouter_message(b.id, "toi", "Code Python")
    historique.ajouter_message(b.id, "gemini", "Voici une boucle for")
    assert [c.titre for c in historique.lister("phares")] == ["Les phares"]
    assert [c.titre for c in historique.lister("boucle")] == ["Code Python"]


def test_recherche_sans_jokers(historique):
    c = historique.creer()
    historique.ajouter_message(c.id, "toi", "Bonjour")
    assert historique.lister("%") == []
    assert historique.lister("_") == []


def test_periode(historique, horloge):
    ancienne = historique.creer()
    historique.ajouter_message(ancienne.id, "toi", "Il y a longtemps")
    horloge.avancer(days=10)
    recente = historique.creer()
    historique.ajouter_message(recente.id, "toi", "Récente")
    assert [c.titre for c in historique.lister(periode="7j")] == ["Récente"]
    assert len(historique.lister(periode="30j")) == 2


def test_supprimer(historique):
    c = historique.creer()
    historique.ajouter_message(c.id, "toi", "Bonjour")
    historique.supprimer(c.id)
    assert historique.lister() == []
    with pytest.raises(ConversationInconnue):
        historique.messages(c.id)


def test_conversation_inconnue(historique):
    with pytest.raises(ConversationInconnue):
        historique.conversation("nexistepas")
    with pytest.raises(ConversationInconnue):
        historique.ajouter_message("nexistepas", "toi", "x")


def test_statistiques(historique):
    a = historique.creer()
    historique.ajouter_message(a.id, "toi", "Q1")
    historique.ajouter_message(a.id, "gemini", "R1", modele="3.1 Pro", duree=10.0)
    historique.ajouter_message(a.id, "toi", "Q2")
    historique.ajouter_message(a.id, "gemini", "R2", modele="3.1 Pro", duree=20.0)
    b = historique.creer()
    historique.ajouter_message(b.id, "toi", "Q3")
    historique.ajouter_message(b.id, "gemini", "R3", modele="4 Argon", duree=6.0)
    assert historique.statistiques("7j") == {
        "conversations": 2, "messages": 3, "modele_favori": "3.1 Pro", "temps_moyen": 12.0,
    }


def test_statistiques_vides(historique):
    assert historique.statistiques("tout") == {
        "conversations": 0, "messages": 0, "modele_favori": None, "temps_moyen": None,
    }


def test_base_corrompue_mise_de_cote(tmp_path, horloge):
    fichier = tmp_path / "historique.db"
    fichier.write_bytes(b"ceci n'est pas une base SQLite " * 10)
    h = Historique(fichier, horloge)
    c = h.creer()
    h.ajouter_message(c.id, "toi", "Bonjour")
    assert len(h.lister()) == 1
    assert (tmp_path / "historique.corrompu.db").exists()
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_historique.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'agent_first.historique'`

- [ ] **Step 3 : Écrire `agent_first/historique.py`**

```python
"""Historique de l'app : conversations et messages, dans une base SQLite sur le PC."""
import logging
import os
import sqlite3
import threading
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

journal = logging.getLogger(__name__)

JOURS_PAR_PERIODE = {"7j": 7, "30j": 30, "tout": None}
LONGUEUR_TITRE = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    titre TEXT NOT NULL DEFAULT '',
    adresse TEXT,
    modele TEXT,
    niveau TEXT,
    cree_le TEXT NOT NULL,
    modifie_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    texte TEXT NOT NULL,
    html TEXT,
    modele TEXT,
    niveau TEXT,
    duree REAL,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id);
"""
COLONNES_CONVERSATION = """c.id, c.titre, c.adresse, c.modele, c.niveau, c.cree_le, c.modifie_le,
    (SELECT count(*) FROM messages m WHERE m.conversation_id = c.id) AS nb_messages"""
COLONNES_MESSAGE = "id, conversation_id, role, texte, html, modele, niveau, duree, cree_le"
NON_VIDE = "EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)"


class ConversationInconnue(KeyError):
    pass


@dataclass(frozen=True)
class Conversation:
    id: str
    titre: str
    adresse: str | None
    modele: str | None
    niveau: str | None
    cree_le: str
    modifie_le: str
    nb_messages: int = 0


@dataclass(frozen=True)
class Message:
    id: int
    conversation_id: str
    role: str
    texte: str
    html: str | None
    modele: str | None
    niveau: str | None
    duree: float | None
    cree_le: str


def titre_depuis(texte: str) -> str:
    titre = " ".join(texte.split())
    return titre if len(titre) <= LONGUEUR_TITRE else titre[: LONGUEUR_TITRE - 1] + "…"


class Historique:
    def __init__(self, fichier: Path, maintenant: Callable[[], datetime] = datetime.now) -> None:
        self._fichier = fichier
        self._maintenant = maintenant
        self._verrou = threading.Lock()
        self._base = self._ouvrir()

    # ---- conversations --------------------------------------------------

    def creer(self, modele: str | None = None, niveau: str | None = None) -> Conversation:
        with self._verrou:
            identifiant, date = uuid.uuid4().hex, self._date()
            self._base.execute(
                "INSERT INTO conversations (id, modele, niveau, cree_le, modifie_le) VALUES (?, ?, ?, ?, ?)",
                (identifiant, modele, niveau, date, date),
            )
            self._base.commit()
            return self._conversation(identifiant)

    def conversation(self, identifiant: str) -> Conversation:
        with self._verrou:
            return self._conversation(identifiant)

    def lister(self, recherche: str = "", periode: str = "tout") -> list[Conversation]:
        motif, depuis = recherche.strip().lower(), self._depuis(periode)
        with self._verrou:
            lignes = self._base.execute(
                f"""SELECT {COLONNES_CONVERSATION} FROM conversations c
                    WHERE {NON_VIDE}
                      AND (? IS NULL OR c.modifie_le >= ?)
                      AND (? = '' OR instr(lower(c.titre), ?) > 0
                           OR EXISTS (SELECT 1 FROM messages m
                                      WHERE m.conversation_id = c.id AND instr(lower(m.texte), ?) > 0))
                    ORDER BY c.modifie_le DESC, c.rowid DESC""",
                (depuis, depuis, motif, motif, motif),
            ).fetchall()
        return [Conversation(**dict(ligne)) for ligne in lignes]

    def enregistrer_adresse(self, identifiant: str, adresse: str) -> None:
        with self._verrou:
            self._conversation(identifiant)
            self._base.execute("UPDATE conversations SET adresse = ? WHERE id = ?", (adresse, identifiant))
            self._base.commit()

    def supprimer(self, identifiant: str) -> None:
        with self._verrou:
            self._conversation(identifiant)
            self._base.execute("DELETE FROM conversations WHERE id = ?", (identifiant,))
            self._base.commit()

    # ---- messages -------------------------------------------------------

    def messages(self, identifiant: str) -> list[Message]:
        with self._verrou:
            self._conversation(identifiant)
            lignes = self._base.execute(
                f"SELECT {COLONNES_MESSAGE} FROM messages WHERE conversation_id = ? ORDER BY id", (identifiant,)
            ).fetchall()
        return [Message(**dict(ligne)) for ligne in lignes]

    def ajouter_message(
        self,
        identifiant: str,
        role: str,
        texte: str,
        html: str | None = None,
        modele: str | None = None,
        niveau: str | None = None,
        duree: float | None = None,
    ) -> Message:
        with self._verrou:
            conversation = self._conversation(identifiant)
            date = self._date()
            curseur = self._base.execute(
                """INSERT INTO messages (conversation_id, role, texte, html, modele, niveau, duree, cree_le)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (identifiant, role, texte, html, modele, niveau, duree, date),
            )
            titre = conversation.titre or (titre_depuis(texte) if role == "toi" else "")
            self._base.execute(
                """UPDATE conversations SET titre = ?, modifie_le = ?,
                   modele = coalesce(?, modele), niveau = coalesce(?, niveau) WHERE id = ?""",
                (titre, date, modele, niveau, identifiant),
            )
            self._base.commit()
            ligne = self._base.execute(
                f"SELECT {COLONNES_MESSAGE} FROM messages WHERE id = ?", (curseur.lastrowid,)
            ).fetchone()
        return Message(**dict(ligne))

    # ---- statistiques ---------------------------------------------------

    def statistiques(self, periode: str = "7j") -> dict:
        depuis = self._depuis(periode)
        with self._verrou:
            conversations = self._base.execute(
                f"SELECT count(*) FROM conversations c WHERE {NON_VIDE} AND (? IS NULL OR c.modifie_le >= ?)",
                (depuis, depuis),
            ).fetchone()[0]
            messages = self._base.execute(
                "SELECT count(*) FROM messages WHERE role = 'toi' AND (? IS NULL OR cree_le >= ?)", (depuis, depuis)
            ).fetchone()[0]
            reponses = self._base.execute(
                "SELECT modele, duree FROM messages WHERE role = 'gemini' AND (? IS NULL OR cree_le >= ?)",
                (depuis, depuis),
            ).fetchall()
        modeles = Counter(r["modele"] for r in reponses if r["modele"])
        durees = [r["duree"] for r in reponses if r["duree"] is not None]
        return {
            "conversations": conversations,
            "messages": messages,
            "modele_favori": modeles.most_common(1)[0][0] if modeles else None,
            "temps_moyen": round(sum(durees) / len(durees), 1) if durees else None,
        }

    # ---- interne --------------------------------------------------------

    def _conversation(self, identifiant: str) -> Conversation:
        ligne = self._base.execute(
            f"SELECT {COLONNES_CONVERSATION} FROM conversations c WHERE c.id = ?", (identifiant,)
        ).fetchone()
        if ligne is None:
            raise ConversationInconnue(identifiant)
        return Conversation(**dict(ligne))

    def _date(self) -> str:
        return self._maintenant().isoformat(timespec="seconds")

    def _depuis(self, periode: str) -> str | None:
        jours = JOURS_PAR_PERIODE[periode]
        if jours is None:
            return None
        return (self._maintenant() - timedelta(days=jours)).isoformat(timespec="seconds")

    def _ouvrir(self) -> sqlite3.Connection:
        self._fichier.parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._connecter()
        except sqlite3.DatabaseError:
            mis_de_cote = self._fichier.with_name(self._fichier.stem + ".corrompu.db")
            os.replace(self._fichier, mis_de_cote)
            journal.warning("%s illisible, mis de côté dans %s", self._fichier, mis_de_cote)
            return self._connecter()

    def _connecter(self) -> sqlite3.Connection:
        base = sqlite3.connect(self._fichier, check_same_thread=False)
        try:
            base.row_factory = sqlite3.Row
            base.execute("PRAGMA foreign_keys = ON")
            base.executescript(SCHEMA)
        except sqlite3.DatabaseError:
            base.close()
            raise
        return base
```

- [ ] **Step 4 : Vérifier qu'ils passent**

Run : `.venv\Scripts\python -m pytest -v`
Expected : 67 passed

- [ ] **Step 5 : Commit**

```bash
git add agent_first/historique.py tests/test_historique.py
git commit -m "feat: historique SQLite des conversations et messages"
git push
```

---

### Task 5 : API v2 d'Agent First, retrait de la fenêtre v1

**Files :**
- Modify : `agent_first/serveur.py` (réécrit), `agent_first/__main__.py`, `config.py`, `requirements.txt` (retrait de `customtkinter`), `demarrer.bat`
- Delete : `gui/` (tout le dossier), `agent_first/conversations.py`, `tests/test_conversations.py`, `tests/test_client.py`, `tests/test_fenetre.py`, `tests/test_correctif_tcl.py`
- Test : `tests/test_serveur.py` (réécrit)

**Interfaces :**
- Consumes : `FileAttente.soumettre`, `Historique`, `ConversationInconnue`, `nettoyer_html`, `Modes`, `Option`, `ResultatGemini`, `ErreurPilote`, `ModeleIntrouvable`, `NiveauIntrouvable`, `PiloteGemini`
- Produces : `creer_app(file, historique, delai, chrome_lance, modes_par_defaut) -> FastAPI` avec :
  - `GET /api/etat` → `{"agent_first": true, "chrome": bool, "google": bool|null}`
  - `GET /api/modeles` → `{"modeles": [{nom, description, actif}], "niveaux": [...]}` (lu dans Gemini puis gardé ; défauts si Chrome fermé ; relu après `ModeleIntrouvable`/`NiveauIntrouvable`)
  - `GET /api/conversations?recherche=&periode=7j|30j|tout` → `[Conversation]`
  - `POST /api/conversations` `{modele?, niveau?}` → `Conversation`
  - `GET /api/conversations/{id}` → `{"conversation": Conversation, "messages": [Message]}` ; 404 `{"erreur"}`
  - `DELETE /api/conversations/{id}` → `{"supprimee": true}` ; 404
  - `POST /api/conversations/{id}/messages` `{texte, modele?, niveau?}` → `{"message": Message}` (la réponse de Gemini) ; erreurs `{"erreur"}` 404/422/502/504/500, enregistrées comme message `erreur`
  - `GET /api/statistiques?periode=7j|30j|tout` → `{conversations, messages, modele_favori, temps_moyen}`
  - `config` : `FICHIER_HISTORIQUE`, `MODELES_PAR_DEFAUT`, `NIVEAUX_PAR_DEFAUT` (et plus de `FICHIER_CONVERSATIONS` ni `DELAI_GUI`)

- [ ] **Step 1 : Réécrire les tests (ils échouent)**

`tests/test_serveur.py` :
```python
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from agent_first.serveur import creer_app
from pilote.erreurs import ModeleIntrouvable, PasConnecteGoogle
from pilote.modeles import Modes, Option, ResultatGemini

PAR_DEFAUT = Modes([Option("4 Argon", "Tâches complexes")], [Option("Min.", "Rapide et efficace")])


class FauxPilote:
    def __init__(self) -> None:
        self.recus: list[tuple] = []
        self.erreur: Exception | None = None
        self.duree = 0.0
        self.listes = 0

    def envoyer(self, adresse, texte, modele=None, niveau=None):
        self.recus.append((adresse, texte, modele, niveau))
        time.sleep(self.duree)
        if self.erreur:
            raise self.erreur
        return ResultatGemini(
            reponse=f"écho : {texte}",
            adresse="https://gemini.google.com/app/1",
            html=f"<p>écho : {texte}</p><script>x()</script>",
            modele=modele,
            niveau=niveau,
            duree=1.5,
        )

    def est_connecte(self):
        return True

    def lister_modes(self):
        self.listes += 1
        return Modes([Option("3.1 Pro", "Raisonnement avancé", True)], [Option("Max.", "Très poussé", True)])


@pytest.fixture
def pilote():
    return FauxPilote()


def demarrer(pilote, tmp_path, delai=2.0, chrome=True):
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, Historique(tmp_path / "historique.db"), delai, lambda: chrome, PAR_DEFAUT)
    return TestClient(app), file


@pytest.fixture
def client(pilote, tmp_path):
    client, file = demarrer(pilote, tmp_path)
    yield client
    file.arreter()


def nouvelle(client, **reglages) -> str:
    return client.post("/api/conversations", json=reglages).json()["id"]


def envoyer(client, conversation, texte, **reglages):
    return client.post(f"/api/conversations/{conversation}/messages", json={"texte": texte, **reglages})


def roles(client, conversation):
    return [m["role"] for m in client.get(f"/api/conversations/{conversation}").json()["messages"]]


def test_modeles_lus_dans_gemini_puis_gardes(client, pilote):
    lus = client.get("/api/modeles").json()
    client.get("/api/modeles")
    assert lus == {
        "modeles": [{"nom": "3.1 Pro", "description": "Raisonnement avancé", "actif": True}],
        "niveaux": [{"nom": "Max.", "description": "Très poussé", "actif": True}],
    }
    assert pilote.listes == 1


def test_modeles_par_defaut_si_chrome_ferme(pilote, tmp_path):
    client, file = demarrer(pilote, tmp_path, chrome=False)
    assert client.get("/api/modeles").json()["modeles"][0]["nom"] == "4 Argon"
    assert pilote.listes == 0
    file.arreter()


def test_conversation_complete(client, pilote):
    conversation = nouvelle(client)
    r = envoyer(client, conversation, "Bonjour", modele="3.1 Pro", niveau="Max.")
    assert r.status_code == 200
    m = r.json()["message"]
    assert (m["role"], m["texte"], m["modele"], m["niveau"], m["duree"]) == ("gemini", "écho : Bonjour", "3.1 Pro", "Max.", 1.5)
    envoyer(client, conversation, "Et ensuite ?", modele="3.1 Pro", niveau="Max.")
    assert pilote.recus == [
        (None, "Bonjour", "3.1 Pro", "Max."),
        ("https://gemini.google.com/app/1", "Et ensuite ?", "3.1 Pro", "Max."),
    ]
    lue = client.get(f"/api/conversations/{conversation}").json()
    assert lue["conversation"]["titre"] == "Bonjour"
    assert [m["role"] for m in lue["messages"]] == ["toi", "gemini", "toi", "gemini"]


def test_reponse_html_nettoyee(client):
    m = envoyer(client, nouvelle(client), "Bonjour").json()["message"]
    assert m["html"] == "<p>écho : Bonjour</p>"


def test_erreur_pilote_enregistree(client, pilote):
    pilote.erreur = PasConnecteGoogle()
    conversation = nouvelle(client)
    r = envoyer(client, conversation, "Bonjour")
    assert r.status_code == 502
    assert r.json()["erreur"] == str(PasConnecteGoogle())
    assert roles(client, conversation) == ["toi", "erreur"]


def test_message_vide_refuse(client, pilote):
    r = envoyer(client, nouvelle(client), "  \n ")
    assert r.status_code == 422
    assert "erreur" in r.json()
    assert pilote.recus == []


def test_conversation_inconnue(client):
    assert envoyer(client, "nexistepas", "Bonjour").status_code == 404
    assert client.get("/api/conversations/nexistepas").status_code == 404
    assert client.delete("/api/conversations/nexistepas").status_code == 404


def test_liste_et_recherche(client):
    envoyer(client, nouvelle(client), "Les phares")
    envoyer(client, nouvelle(client), "Code Python")
    assert [c["titre"] for c in client.get("/api/conversations").json()] == ["Code Python", "Les phares"]
    trouvees = client.get("/api/conversations", params={"recherche": "phares"}).json()
    assert [c["titre"] for c in trouvees] == ["Les phares"]


def test_suppression(client):
    conversation = nouvelle(client)
    envoyer(client, conversation, "Bonjour")
    assert client.delete(f"/api/conversations/{conversation}").json() == {"supprimee": True}
    assert client.get(f"/api/conversations/{conversation}").status_code == 404
    assert client.get("/api/conversations").json() == []


def test_suppression_pendant_envoi(pilote, tmp_path):
    pilote.duree = 0.5
    client, file = demarrer(pilote, tmp_path)
    conversation = nouvelle(client)
    with ThreadPoolExecutor(1) as fil:
        envoi = fil.submit(envoyer, client, conversation, "Bonjour")
        time.sleep(0.2)
        client.delete(f"/api/conversations/{conversation}")
        r = envoi.result(timeout=5)
    assert r.status_code == 200
    assert r.json()["message"]["texte"] == "écho : Bonjour"
    assert client.get(f"/api/conversations/{conversation}").status_code == 404
    file.arreter()


def test_statistiques(client):
    envoyer(client, nouvelle(client), "Bonjour", modele="3.1 Pro")
    assert client.get("/api/statistiques", params={"periode": "7j"}).json() == {
        "conversations": 1, "messages": 1, "modele_favori": "3.1 Pro", "temps_moyen": 1.5,
    }


def test_modele_introuvable_relit_la_liste(client, pilote):
    client.get("/api/modeles")
    pilote.erreur = ModeleIntrouvable("9 Zeta")
    r = envoyer(client, nouvelle(client), "Bonjour", modele="9 Zeta")
    assert r.status_code == 502
    assert "9 Zeta" in r.json()["erreur"]
    client.get("/api/modeles")
    assert pilote.listes == 2


def test_delai_depasse(pilote, tmp_path):
    pilote.duree = 1.0
    client, file = demarrer(pilote, tmp_path, delai=0.1)
    conversation = nouvelle(client)
    assert envoyer(client, conversation, "Bonjour").status_code == 504
    assert roles(client, conversation) == ["toi", "erreur"]
    file.arreter()


def test_etat(client):
    assert client.get("/api/etat").json() == {"agent_first": True, "chrome": True, "google": True}
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_serveur.py -v`
Expected : FAIL (la v1 de `creer_app` attend une `MemoireConversations` et n'a pas de routes `/api/...`).

- [ ] **Step 3 : Réécrire `agent_first/serveur.py`**

```python
"""API HTTP locale d'Agent First (n'écoute que sur 127.0.0.1)."""
import logging
from concurrent.futures import TimeoutError as DelaiFutur
from dataclasses import asdict
from typing import Callable, Literal

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from agent_first.file_attente import FileAttente
from agent_first.historique import ConversationInconnue, Historique
from agent_first.nettoyage import nettoyer_html
from pilote.erreurs import ErreurPilote, ModeleIntrouvable, NiveauIntrouvable
from pilote.modeles import Modes, ResultatGemini

journal = logging.getLogger(__name__)

Periode = Literal["7j", "30j", "tout"]
INCONNUE = "Conversation inconnue : démarre une nouvelle conversation."


class NouvelleConversation(BaseModel):
    modele: str | None = None
    niveau: str | None = None


class NouveauMessage(BaseModel):
    texte: str
    modele: str | None = None
    niveau: str | None = None

    @field_validator("texte")
    @classmethod
    def texte_non_vide(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("le message est vide")
        return valeur


def erreur(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"erreur": message})


def creer_app(
    file: FileAttente,
    historique: Historique,
    delai: float,
    chrome_lance: Callable[[], bool],
    modes_par_defaut: Modes,
) -> FastAPI:
    app = FastAPI(title="Agent First")
    cache: dict[str, Modes] = {}

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, _exc):
        return erreur(422, "Message vide ou demande invalide.")

    @app.get("/api/etat")
    def etat():
        lance = chrome_lance()
        google = None
        if lance:
            try:
                google = file.soumettre(lambda pilote: pilote.est_connecte()).result(timeout=5)
            except Exception:
                google = None  # occupé ou injoignable : inconnu
        return {"agent_first": True, "chrome": lance, "google": google}

    @app.get("/api/modeles")
    def modeles():
        modes = cache.get("modes")
        if modes is None and chrome_lance():
            try:
                lus = file.soumettre(lambda pilote: pilote.lister_modes()).result(timeout=30)
                if lus.modeles:
                    cache["modes"] = modes = lus
            except Exception:
                journal.warning("Modèles illisibles dans Gemini : liste par défaut", exc_info=True)
        return asdict(modes or modes_par_defaut)

    @app.get("/api/conversations")
    def conversations(recherche: str = "", periode: Periode = "tout"):
        return [asdict(c) for c in historique.lister(recherche, periode)]

    @app.post("/api/conversations")
    def nouvelle_conversation(demande: NouvelleConversation | None = None):
        reglages = demande or NouvelleConversation()
        return asdict(historique.creer(reglages.modele, reglages.niveau))

    @app.get("/api/conversations/{identifiant}")
    def conversation(identifiant: str):
        try:
            lue = historique.conversation(identifiant)
            messages = historique.messages(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        return {"conversation": asdict(lue), "messages": [asdict(m) for m in messages]}

    @app.delete("/api/conversations/{identifiant}")
    def supprimer(identifiant: str):
        try:
            historique.supprimer(identifiant)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        return {"supprimee": True}

    @app.post("/api/conversations/{identifiant}/messages")
    def envoyer(identifiant: str, demande: NouveauMessage):
        try:
            adresse = historique.conversation(identifiant).adresse
            historique.ajouter_message(identifiant, "toi", demande.texte, modele=demande.modele, niveau=demande.niveau)
        except ConversationInconnue:
            return erreur(404, INCONNUE)
        futur = file.soumettre(lambda pilote: pilote.envoyer(adresse, demande.texte, demande.modele, demande.niveau))
        try:
            resultat = futur.result(timeout=delai)
        except DelaiFutur:
            return echec(identifiant, 504, f"Pas de réponse de Gemini après {delai:.0f} s.")
        except (ModeleIntrouvable, NiveauIntrouvable) as e:
            cache.pop("modes", None)  # la liste a changé : relue à la prochaine demande
            return echec(identifiant, 502, str(e))
        except ErreurPilote as e:
            return echec(identifiant, 502, str(e))
        except Exception as e:
            journal.exception("Erreur inattendue pendant l'envoi")
            return echec(identifiant, 500, f"Erreur inattendue : {e}")
        return {"message": enregistrer_reponse(identifiant, resultat)}

    @app.get("/api/statistiques")
    def statistiques(periode: Periode = "7j"):
        return historique.statistiques(periode)

    def enregistrer_reponse(identifiant: str, resultat: ResultatGemini) -> dict:
        html = nettoyer_html(resultat.html) if resultat.html else None
        try:
            historique.enregistrer_adresse(identifiant, resultat.adresse)
            message = historique.ajouter_message(
                identifiant, "gemini", resultat.reponse, html=html,
                modele=resultat.modele, niveau=resultat.niveau, duree=resultat.duree,
            )
        except ConversationInconnue:
            journal.info("Conversation %s supprimée pendant l'envoi : réponse non enregistrée", identifiant)
            return {
                "id": None, "conversation_id": identifiant, "role": "gemini", "texte": resultat.reponse,
                "html": html, "modele": resultat.modele, "niveau": resultat.niveau,
                "duree": resultat.duree, "cree_le": None,
            }
        return asdict(message)

    def echec(identifiant: str, code: int, message: str) -> JSONResponse:
        try:
            historique.ajouter_message(identifiant, "erreur", message)
        except ConversationInconnue:
            pass
        return erreur(code, message)

    return app
```

- [ ] **Step 4 : `config.py`, `agent_first/__main__.py`, `demarrer.bat`**

Dans `config.py` : supprimer `DELAI_GUI` et `FICHIER_CONVERSATIONS`, ajouter :
```python
FICHIER_HISTORIQUE = DOSSIER_DONNEES / "historique.db"

# Utilisés tant que la liste n'a pas pu être lue dans Gemini (relevés le 2026-10-15).
MODELES_PAR_DEFAUT = [
    ("3.5 Flash-Lite", "Réponses les plus rapides"),
    ("3.8 Flash", "Aide polyvalente"),
    ("3.1 Pro", "Raisonnement avancé"),
    ("4 Argon", "Tâches complexes"),
]
NIVEAUX_PAR_DEFAUT = [("Min.", "Rapide et efficace"), ("Moyen", "Équilibré"), ("Max.", "Très poussé")]
```

Dans `agent_first/__main__.py` : remplacer l'import `MemoireConversations` par
```python
from agent_first.historique import Historique
from pilote.modeles import Modes, Option
```
et les lignes `memoire = ...` / `app = creer_app(...)` par :
```python
    historique = Historique(config.FICHIER_HISTORIQUE)
    par_defaut = Modes(
        [Option(nom, description) for nom, description in config.MODELES_PAR_DEFAUT],
        [Option(nom, description) for nom, description in config.NIVEAUX_PAR_DEFAUT],
    )
    app = creer_app(file, historique, config.DELAI_AGENT, chrome.est_lance, par_defaut)
```

`demarrer.bat` (la fenêtre d'app arrive au plan B) :
```bat
@echo off
cd /d "%~dp0"
start "Agent First" .venv\Scripts\python.exe -m agent_first
```

Dans `requirements.txt` : retirer la ligne `customtkinter>=5.2`.

- [ ] **Step 5 : Retirer la v1 GUI**

Run :
```
git rm -r -q gui agent_first/conversations.py tests/test_conversations.py tests/test_client.py tests/test_fenetre.py tests/test_correctif_tcl.py
```

- [ ] **Step 6 : Tous les tests**

Run : `.venv\Scripts\python -m pytest -v`
Expected : 55 passed (67 − 26 retirés dont les 7 anciens tests serveur + 14 nouveaux ; soit attente 5, chrome 3, file 4, modes 4, réglages 5, nettoyage 7, historique 13, serveur 14)

- [ ] **Step 7 : Vérification réelle de bout en bout (sans interface)**

Démarrer `.venv\Scripts\python -m agent_first`, puis avec un petit script httpx :
1. `GET /api/modeles` → les 4 modèles lus dans Gemini, avec `actif`.
2. `POST /api/conversations` puis `POST /api/conversations/{id}/messages` `{"texte": "Réponds en français : un titre et une liste de 2 éléments.", "modele": "3.8 Flash", "niveau": "Moyen"}` → `message.html` contient `<h`/`<li>` et pas de `<button` ; `modele` = « 3.8 Flash ».
3. 2ᵉ message dans la même conversation → même conversation Gemini (`GET /api/conversations/{id}` : adresse inchangée, 4 messages).
4. `GET /api/conversations?recherche=liste` → la conversation ; `GET /api/statistiques` → 1 conversation, 2 messages, modèle favori « 3.8 Flash ».
5. Arrêter Agent First ; remettre `python -m pilote.modes --modele "4 Argon" --niveau "Min."`.

- [ ] **Step 8 : Commit**

```bash
git add -A agent_first config.py requirements.txt demarrer.bat tests
git commit -m "feat: API v2 d'Agent First (historique, modèles) et retrait de la fenêtre v1"
git push
```
