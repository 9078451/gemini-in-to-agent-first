# Gemini web ↔ Agent First — plan de réalisation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une fenêtre GUI où l'on écrit à Gemini ; Agent First reçoit le
message, pilote un Chrome dédié connecté à Google sur `gemini.google.com`, lit
la réponse et la renvoie à la fenêtre.

**Architecture :** trois programmes Python séparés. `gui/` (fenêtre
CustomTkinter) parle en HTTP à `agent_first/` (FastAPI sur 127.0.0.1:8765,
file d'attente à un seul fil, mémoire des conversations en JSON), qui appelle
`pilote/` (Playwright branché par CDP sur un vrai Chrome lancé avec un profil
dédié).

**Tech Stack :** Python 3.13, Playwright (API synchrone, `connect_over_cdp`),
FastAPI + Uvicorn, httpx, CustomTkinter, pytest.

**Spec :** `docs/superpowers/specs/2026-10-15-gemini-agent-first-design.md`

## Global Constraints

- Windows 11, Python 3.13, Chrome installé à `C:\Program Files\Google\Chrome\Application\chrome.exe`.
- Agent First n'écoute que sur `127.0.0.1:8765`. Port de débogage Chrome : `9222` (local).
- Délai max d'une réponse Gemini : 180 s. Réponse finie = bouton « Arrêter » absent **et** texte inchangé pendant 2 s.
- Attente max côté GUI : 5 minutes (300 s) ; côté serveur : 290 s.
- Chrome est lancé avec le profil dédié `profil-chrome-gemini/`, jamais le profil Chrome habituel.
- Tous les repères de la page Gemini sont dans `pilote/selecteurs.py`, nulle part ailleurs.
- Une vérification Google / captcha n'est **jamais** contournée : on demande à l'utilisateur de la faire.
- Tous les textes visibles par l'utilisateur sont en français.
- `profil-chrome-gemini/`, `donnees/`, `journaux/`, `.venv/` sont exclus de git.
- Playwright (synchrone) n'est utilisé que depuis le fil qui l'a créé : dans Agent First, uniquement le fil de la file d'attente.
- Git : dépôt déjà créé, branche `main`, distant `origin` = `https://github.com/9078451/gemini-in-to-agent-first.git`. Chaque commit se termine par la ligne `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` et est suivi de `git push`.
- Fenêtre : thème sombre de la fiche (section 4.1 « Style visuel »), couleurs uniquement dans `gui/theme.py`.

## Review Focus

1. **Message sur plusieurs lignes** : doit partir en un seul message, pas coupé à chaque retour à la ligne → vérification réelle dans la tâche 4 (étape 4).
2. **Suite d'une conversation existante** : une ancienne réponse affichée pendant le chargement ne doit pas être prise pour la nouvelle → `_attendre_historique` + vérification réelle `--suite` dans la tâche 4 (étape 4).
3. **Message vide ou seulement des espaces** : refusé avant d'atteindre Gemini → test `test_message_vide_refuse` (tâche 7) ; la fenêtre ignore un envoi vide (tâche 9).
4. **`donnees/conversations.json` corrompu ou conversation inconnue** : Agent First démarre quand même, et la fenêtre reçoit un message clair → tests `test_fichier_corrompu_*` (tâche 5) et `test_conversation_inconnue` (tâche 7).
5. **Chrome dédié fermé par l'utilisateur entre deux messages** : relancé et rebranché au message suivant → `ChromeDedie.page()` (tâche 2) + vérification réelle dans la tâche 4 (étape 4).

---

## Phase 1 — Pilote navigateur

### Task 1 : Base du projet + attente de fin de réponse

**Files :**
- Create : `requirements.txt`, `pytest.ini`, `.gitignore`, `config.py`
- Create : `pilote/__init__.py`, `pilote/erreurs.py`, `pilote/modeles.py`, `pilote/attente.py`
- Test : `tests/test_attente.py`

**Interfaces :**
- Produces :
  - `config` : `RACINE, CHEMIN_CHROME, DOSSIER_PROFIL, PORT_CHROME, URL_GEMINI, HOTE_AGENT, PORT_AGENT, DELAI_REPONSE, STABILITE, DELAI_AGENT, DELAI_GUI, DOSSIER_DONNEES, DOSSIER_JOURNAUX, FICHIER_CONVERSATIONS`
  - `pilote.erreurs` : `ErreurPilote`, `ChromeInjoignable()`, `PasConnecteGoogle()`, `VerificationGoogle()`, `RepereIntrouvable(nom: str, capture: str | None = None)`, `DelaiDepasse(delai: float, partiel: str)` ; `str(erreur)` = message pour l'utilisateur.
  - `pilote.modeles` : `ResultatGemini(reponse: str, adresse: str)` ; protocole `Pilote` avec `envoyer(adresse: str | None, texte: str) -> ResultatGemini` et `est_connecte() -> bool`.
  - `pilote.attente.attendre_fin_reponse(lire_texte, generation_en_cours, delai_max, stabilite, intervalle=0.5, horloge=time.monotonic, dormir=time.sleep) -> str`

- [ ] **Step 1 : Fichiers de base**

`requirements.txt` :
```
playwright>=1.48
fastapi>=0.115
uvicorn>=0.30
httpx>=0.27
customtkinter>=5.2
pytest>=8.0
```

`pytest.ini` :
```ini
[pytest]
testpaths = tests
pythonpath = .
```

`.gitignore` :
```
.venv/
__pycache__/
.pytest_cache/
profil-chrome-gemini/
donnees/
journaux/
```

`config.py` :
```python
"""Réglages communs : chemins, ports et délais."""
from pathlib import Path

RACINE = Path(__file__).resolve().parent

CHEMIN_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DOSSIER_PROFIL = RACINE / "profil-chrome-gemini"
PORT_CHROME = 9222
URL_GEMINI = "https://gemini.google.com/app"

HOTE_AGENT = "127.0.0.1"
PORT_AGENT = 8765

DELAI_REPONSE = 180.0  # secondes max pour qu'une réponse Gemini se termine
STABILITE = 2.0  # secondes sans changement du texte = réponse finie
DELAI_AGENT = 290.0  # attente max d'Agent First (file d'attente + Gemini)
DELAI_GUI = 300.0  # attente max de la fenêtre

DOSSIER_DONNEES = RACINE / "donnees"
DOSSIER_JOURNAUX = RACINE / "journaux"
FICHIER_CONVERSATIONS = DOSSIER_DONNEES / "conversations.json"
```

`pilote/__init__.py` : fichier vide.

- [ ] **Step 2 : Environnement Python**

Run : `python -m venv .venv` puis `.venv\Scripts\python -m pip install -r requirements.txt`
Expected : installation sans erreur. (Pas besoin de `playwright install` : on se branche sur le Chrome déjà installé.)

- [ ] **Step 3 : Erreurs et modèles**

`pilote/erreurs.py` :
```python
"""Erreurs du pilote. Le texte de chaque erreur est destiné à l'utilisateur."""


class ErreurPilote(Exception):
    """Base de toutes les erreurs du pilote navigateur."""


class ChromeInjoignable(ErreurPilote):
    def __init__(self) -> None:
        super().__init__("Impossible de joindre le Chrome dédié (port de débogage fermé).")


class PasConnecteGoogle(ErreurPilote):
    def __init__(self) -> None:
        super().__init__(
            "Connecte-toi à Google dans la fenêtre Chrome dédiée, puis renvoie ton message."
        )


class VerificationGoogle(ErreurPilote):
    def __init__(self) -> None:
        super().__init__(
            "Google demande une vérification : fais-la toi-même dans la fenêtre "
            "Chrome dédiée, puis renvoie ton message."
        )


class RepereIntrouvable(ErreurPilote):
    def __init__(self, nom: str, capture: str | None = None) -> None:
        self.nom = nom
        self.capture = capture
        message = f"Repère « {nom} » introuvable : Gemini a peut-être changé son interface."
        if capture:
            message += f" Capture d'écran : {capture}"
        super().__init__(message)


class DelaiDepasse(ErreurPilote):
    def __init__(self, delai: float, partiel: str) -> None:
        self.partiel = partiel
        message = f"Gemini n'a pas fini de répondre après {delai:.0f} s."
        if partiel:
            message += f" Début de la réponse :\n{partiel}"
        super().__init__(message)
```

`pilote/modeles.py` :
```python
"""Ce que le pilote renvoie, et ce qu'Agent First attend d'un pilote."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResultatGemini:
    reponse: str
    adresse: str  # adresse de la conversation, ex. https://gemini.google.com/app/abc123


class Pilote(Protocol):
    def envoyer(self, adresse: str | None, texte: str) -> ResultatGemini: ...

    def est_connecte(self) -> bool: ...
```

- [ ] **Step 4 : Écrire les tests de l'attente (ils échouent)**

`tests/test_attente.py` :
```python
import pytest

from pilote.attente import attendre_fin_reponse
from pilote.erreurs import DelaiDepasse


class Horloge:
    """Fausse horloge : le temps n'avance que quand on « dort »."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def dormir(self, secondes: float) -> None:
        self.t += secondes


def suite_de_textes(*textes: str):
    """Renvoie les textes un par un, puis répète le dernier."""
    restants = list(textes)

    def lire() -> str:
        return restants.pop(0) if len(restants) > 1 else restants[0]

    return lire


def attendre(lire, en_cours, horloge, delai_max=180.0):
    return attendre_fin_reponse(
        lire, en_cours, delai_max=delai_max, stabilite=2.0,
        intervalle=0.5, horloge=horloge, dormir=horloge.dormir,
    )


def test_texte_stable_rendu_apres_stabilite():
    h = Horloge()
    assert attendre(lambda: "Bonjour", lambda: False, h) == "Bonjour"
    assert h.t == pytest.approx(2.0)


def test_attend_que_le_texte_arrete_de_grandir():
    h = Horloge()
    lire = suite_de_textes("", "Bon", "Bonjour", "Bonjour !")
    assert attendre(lire, lambda: False, h) == "Bonjour !"


def test_attend_la_fin_de_la_generation():
    h = Horloge()
    assert attendre(lambda: "Bonjour", lambda: h.t < 5.0, h) == "Bonjour"
    assert h.t >= 5.0


def test_texte_vide_finit_en_delai_depasse():
    h = Horloge()
    with pytest.raises(DelaiDepasse) as erreur:
        attendre(lambda: "", lambda: False, h, delai_max=10.0)
    assert erreur.value.partiel == ""


def test_generation_sans_fin_renvoie_le_debut():
    h = Horloge()
    with pytest.raises(DelaiDepasse) as erreur:
        attendre(lambda: "Début de réponse", lambda: True, h, delai_max=10.0)
    assert erreur.value.partiel == "Début de réponse"
    assert "Début de réponse" in str(erreur.value)
```

- [ ] **Step 5 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_attente.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'pilote.attente'`

- [ ] **Step 6 : Écrire l'attente**

`pilote/attente.py` :
```python
"""Attendre qu'une réponse de Gemini ait fini de s'écrire."""
import time
from typing import Callable

from pilote.erreurs import DelaiDepasse


def attendre_fin_reponse(
    lire_texte: Callable[[], str],
    generation_en_cours: Callable[[], bool],
    delai_max: float,
    stabilite: float,
    intervalle: float = 0.5,
    horloge: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> str:
    """Renvoie le texte quand la génération est finie et que le texte n'a plus
    bougé pendant `stabilite` secondes. Lève DelaiDepasse après `delai_max`."""
    debut = horloge()
    dernier_texte = lire_texte()
    dernier_changement = debut
    while True:
        maintenant = horloge()
        if maintenant - debut > delai_max:
            raise DelaiDepasse(delai_max, dernier_texte.strip())
        texte = lire_texte()
        if texte != dernier_texte:
            dernier_texte = texte
            dernier_changement = maintenant
        elif (
            texte.strip()
            and not generation_en_cours()
            and maintenant - dernier_changement >= stabilite
        ):
            return texte
        dormir(intervalle)
```

- [ ] **Step 7 : Vérifier qu'ils passent**

Run : `.venv\Scripts\python -m pytest tests/test_attente.py -v`
Expected : 5 passed

- [ ] **Step 8 : Commit**

```bash
git add requirements.txt pytest.ini .gitignore config.py pilote tests
git commit -m "feat: base du projet et attente de fin de réponse Gemini"
git push
```

---

### Task 2 : Chrome dédié

**Files :**
- Create : `pilote/chrome.py`
- Test : `tests/test_chrome.py`

**Interfaces :**
- Consumes : `pilote.erreurs.ChromeInjoignable`
- Produces : `ChromeDedie(chemin_chrome: Path, dossier_profil: Path, port: int, url_accueil: str)` avec
  `commande_lancement() -> list[str]`, `est_lance() -> bool` (utilisable depuis n'importe quel fil),
  `lancer(delai: float = 15.0) -> None`, `page() -> playwright.sync_api.Page` et `fermer() -> None` (ces deux-là : uniquement depuis le fil qui utilise Playwright).

- [ ] **Step 1 : Écrire les tests (ils échouent)**

`tests/test_chrome.py` :
```python
import socket
from pathlib import Path

from pilote.chrome import ChromeDedie


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def nouveau_chrome(port: int = 9222) -> ChromeDedie:
    return ChromeDedie(Path("C:/chrome.exe"), Path("C:/profil"), port, "https://gemini.google.com/app")


def test_commande_utilise_le_profil_dedie_et_le_port():
    commande = nouveau_chrome(9333).commande_lancement()
    assert commande[0] == str(Path("C:/chrome.exe"))
    assert "--remote-debugging-port=9333" in commande
    assert f"--user-data-dir={Path('C:/profil')}" in commande
    assert commande[-1] == "https://gemini.google.com/app"


def test_commande_n_ouvre_pas_le_port_sur_le_reseau():
    commande = nouveau_chrome().commande_lancement()
    assert not any(a.startswith("--remote-debugging-address") for a in commande)


def test_est_lance_faux_si_personne_n_ecoute():
    assert nouveau_chrome(port_libre()).est_lance() is False
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_chrome.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'pilote.chrome'`

- [ ] **Step 3 : Écrire `pilote/chrome.py`**

```python
"""Lancer le Chrome dédié et s'y brancher avec Playwright.

`est_lance` peut être appelé depuis n'importe quel fil ; `page` et `fermer`
uniquement depuis le fil qui utilise Playwright.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright.sync_api import Error as ErreurPlaywright

from pilote.erreurs import ChromeInjoignable


class ChromeDedie:
    def __init__(self, chemin_chrome: Path, dossier_profil: Path, port: int, url_accueil: str) -> None:
        self._chemin_chrome = chemin_chrome
        self._dossier_profil = dossier_profil
        self._port = port
        self._url_accueil = url_accueil
        self._playwright: Playwright | None = None
        self._navigateur: Browser | None = None

    def commande_lancement(self) -> list[str]:
        return [
            str(self._chemin_chrome),
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._dossier_profil}",
            "--no-first-run",
            "--no-default-browser-check",
            self._url_accueil,
        ]

    def est_lance(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/json/version", timeout=1) as reponse:
                json.load(reponse)
            return True
        except (OSError, ValueError):
            return False

    def lancer(self, delai: float = 15.0) -> None:
        self._dossier_profil.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(self.commande_lancement())
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.est_lance():
                return
            time.sleep(0.3)
        raise ChromeInjoignable()

    def page(self) -> Page:
        """Onglet Gemini du Chrome dédié. Lance Chrome et s'y branche si besoin
        (par exemple si l'utilisateur l'a fermé entre deux messages)."""
        if self._navigateur is None or not self._navigateur.is_connected():
            if not self.est_lance():
                self.lancer()
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            try:
                self._navigateur = self._playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{self._port}"
                )
            except ErreurPlaywright as e:
                raise ChromeInjoignable() from e
        contexte = self._navigateur.contexts[0]
        for onglet in contexte.pages:
            if onglet.url.startswith("https://gemini.google.com"):
                return onglet
        onglet = contexte.new_page()
        onglet.goto(self._url_accueil, wait_until="domcontentloaded")
        return onglet

    def fermer(self) -> None:
        """Débranche Playwright. Le Chrome dédié reste ouvert."""
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = None
        self._navigateur = None
```

- [ ] **Step 4 : Vérifier qu'ils passent**

Run : `.venv\Scripts\python -m pytest tests/test_chrome.py -v`
Expected : 3 passed

- [ ] **Step 5 : Vérification réelle + connexion Google (une seule fois, par l'utilisateur)**

Run :
```
.venv\Scripts\python -c "import config; from pilote.chrome import ChromeDedie; c = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI); print(c.page().url); c.fermer()"
```
Expected : une fenêtre Chrome séparée s'ouvre sur Gemini ; la commande affiche une adresse `https://gemini.google.com/...`. **L'utilisateur se connecte à son compte Google dans cette fenêtre, à la main.** Relancer la commande : Chrome n'est pas relancé (déjà ouvert), même résultat.

- [ ] **Step 6 : Commit**

```bash
git add pilote/chrome.py tests/test_chrome.py
git commit -m "feat: lancement du Chrome dédié et branchement Playwright"
git push
```

---

### Task 3 : Repères de la page Gemini + outil d'inspection

**Files :**
- Create : `pilote/selecteurs.py`, `pilote/inspecter.py`

**Interfaces :**
- Consumes : `ChromeDedie` (tâche 2), `config`
- Produces : `pilote.selecteurs.REPERES: dict[str, list[str]]` avec exactement les clés
  `champ_saisie`, `bouton_envoyer`, `bouton_arreter`, `reponse`, `lien_connexion`.

- [ ] **Step 1 : Écrire `pilote/selecteurs.py` (candidats de départ)**

```python
"""Tous les repères de la page Gemini, au même endroit.

Chaque repère a plusieurs candidats CSS, essayés dans l'ordre : le premier qui
trouve au moins un élément est utilisé. Quand Google change son site, c'est
ici qu'on corrige — vérifier avec `python -m pilote.inspecter`.
"""

REPERES: dict[str, list[str]] = {
    "champ_saisie": [
        "rich-textarea div.ql-editor[contenteditable='true']",
        "div[role='textbox'][contenteditable='true']",
    ],
    "bouton_envoyer": [
        "button.send-button:not(.stop)",
        "button[aria-label*='Send']",
        "button[aria-label*='Envoyer']",
    ],
    "bouton_arreter": [
        "button.send-button.stop",
        "button[aria-label*='Stop']",
        "button[aria-label*='Arrêter']",
    ],
    "reponse": [
        "model-response message-content",
        "model-response",
    ],
    "lien_connexion": [
        "a[href*='accounts.google.com/ServiceLogin']",
        "a[href*='accounts.google.com/v3/signin']",
    ],
}
```

- [ ] **Step 2 : Écrire `pilote/inspecter.py`**

```python
"""Montre, pour chaque repère, combien d'éléments chaque candidat trouve.

Usage :
  python -m pilote.inspecter                   compte chaque candidat
  python -m pilote.inspecter --html "CSS"      affiche le HTML du 1er élément trouvé
"""
import argparse
import sys

import config
from pilote.chrome import ChromeDedie
from pilote.selecteurs import REPERES


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspecte la page Gemini du Chrome dédié.")
    parser.add_argument("--html", metavar="CSS", help="affiche le HTML du premier élément trouvé")
    args = parser.parse_args()

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    try:
        page = chrome.page()
        print(f"Page : {page.url}\n")
        if args.html:
            elements = page.locator(args.html)
            if elements.count() == 0:
                print("Aucun élément trouvé.")
            else:
                print(elements.first.evaluate("e => e.outerHTML")[:4000])
            return
        for nom, candidats in REPERES.items():
            print(nom)
            for selecteur in candidats:
                print(f"  {page.locator(selecteur).count():>3}  {selecteur}")
    finally:
        chrome.fermer()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3 : Relever les vrais repères sur la page (Chrome connecté à Google)**

1. Dans le Chrome dédié, poser une question à la main à Gemini et attendre la réponse.
2. Run : `.venv\Scripts\python -m pilote.inspecter`
   Expected : `champ_saisie`, `bouton_envoyer`, `reponse` ont au moins un candidat ≥ 1 ; `lien_connexion` à 0 (connecté) ; `bouton_arreter` à 0 (rien en cours).
3. Reposer une question longue à la main (« écris un texte de 500 mots ») et relancer l'inspection **pendant** qu'elle s'écrit.
   Expected : `bouton_arreter` a un candidat ≥ 1.
4. Pour tout repère à 0 alors qu'il devrait exister : `.venv\Scripts\python -m pilote.inspecter --html "input-area-v2"` (zone de saisie) ou `--html "model-response"` (réponse) ou `--html "button"` (boutons), lire le HTML, et **corriger les candidats dans `pilote/selecteurs.py`** (mettre le candidat qui marche en premier). Relancer l'étape 2 jusqu'à ce que tout soit bon.

- [ ] **Step 4 : Commit**

```bash
git add pilote/selecteurs.py pilote/inspecter.py
git commit -m "feat: repères de la page Gemini et outil d'inspection"
git push
```

---

### Task 4 : Pilote Gemini (taper, envoyer, attendre, lire) + essai réel

**Files :**
- Create : `pilote/gemini.py`, `pilote/essai.py`

**Interfaces :**
- Consumes : `ChromeDedie.page()`, `REPERES`, `attendre_fin_reponse`, erreurs et `ResultatGemini` (tâches 1-3)
- Produces : `PiloteGemini(chrome: ChromeDedie, url_nouvelle: str, delai_reponse: float, stabilite: float, dossier_captures: Path)`
  qui respecte le protocole `Pilote` : `envoyer(adresse: str | None, texte: str) -> ResultatGemini` et `est_connecte() -> bool`.

- [ ] **Step 1 : Écrire `pilote/gemini.py`**

```python
"""Taper un message dans Gemini, attendre la fin de la réponse et la lire."""
import logging
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as ErreurPlaywright
from playwright.sync_api import Locator, Page

from pilote.attente import attendre_fin_reponse
from pilote.chrome import ChromeDedie
from pilote.erreurs import PasConnecteGoogle, RepereIntrouvable, VerificationGoogle
from pilote.modeles import ResultatGemini
from pilote.selecteurs import REPERES

journal = logging.getLogger(__name__)


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

    def envoyer(self, adresse: str | None, texte: str) -> ResultatGemini:
        """Envoie `texte` dans la conversation `adresse` (None = nouvelle conversation)."""
        page = self._chrome.page()
        try:
            return self._envoyer(page, adresse, texte)
        except RepereIntrouvable as e:
            raise RepereIntrouvable(e.nom, self._capturer(page)) from e

    def est_connecte(self) -> bool:
        return not self._demande_connexion(self._chrome.page())

    def _envoyer(self, page: Page, adresse: str | None, texte: str) -> ResultatGemini:
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

        nb_avant = compter(page, "reponse")
        champ.first.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        # insert_text n'appuie sur aucune touche : les retours à la ligne
        # n'envoient pas le message en morceaux.
        page.keyboard.insert_text(texte)
        attendre_repere(page, "bouton_envoyer", 5).first.click()

        nouvelle = self._attendre_nouvelle_reponse(page, nb_avant, 30)
        reponse = attendre_fin_reponse(
            lire_texte=nouvelle.inner_text,
            generation_en_cours=lambda: self._generation_en_cours(page),
            delai_max=self._delai_reponse,
            stabilite=self._stabilite,
        )
        return ResultatGemini(reponse=reponse.strip(), adresse=page.url)

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

    def _attendre_nouvelle_reponse(self, page: Page, nb_avant: int, delai: float) -> Locator:
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            reponses = premier_present(page, "reponse")
            if reponses is not None and reponses.count() > nb_avant:
                return reponses.nth(nb_avant)
            time.sleep(0.3)
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

- [ ] **Step 2 : Écrire `pilote/essai.py`**

```python
"""Essai réel : envoie un message à Gemini et affiche la réponse.

Usage :
  python -m pilote.essai "Bonjour"                     nouvelle conversation
  python -m pilote.essai "Et ensuite ?" --suite URL    continue la conversation URL
Dans le texte, \\n devient un retour à la ligne.
"""
import argparse
import sys

import config
from pilote.chrome import ChromeDedie
from pilote.erreurs import ErreurPilote
from pilote.gemini import PiloteGemini


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Envoie un message à Gemini web.")
    parser.add_argument("texte")
    parser.add_argument("--suite", metavar="URL", help="adresse d'une conversation Gemini à continuer")
    args = parser.parse_args()

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    pilote = PiloteGemini(
        chrome, config.URL_GEMINI, config.DELAI_REPONSE, config.STABILITE, config.DOSSIER_JOURNAUX
    )
    try:
        resultat = pilote.envoyer(args.suite, args.texte.replace("\\n", "\n"))
    except ErreurPilote as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        return 1
    finally:
        chrome.fermer()
    print(resultat.reponse)
    print(f"\n[conversation : {resultat.adresse}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3 : Tous les tests automatiques passent toujours**

Run : `.venv\Scripts\python -m pytest -v`
Expected : 8 passed

- [ ] **Step 4 : Vérifications réelles (Chrome dédié connecté à Google)**

1. `.venv\Scripts\python -m pilote.essai "Réponds juste : bonjour"` → la réponse s'affiche, suivie de `[conversation : https://gemini.google.com/app/...]`.
2. `.venv\Scripts\python -m pilote.essai "Quel mot viens-tu d'écrire ?" --suite <URL de l'étape 1>` → Gemini répond « bonjour » (il se souvient), et ce n'est pas l'ancienne réponse recopiée.
3. `.venv\Scripts\python -m pilote.essai "Ligne 1\nLigne 2\nCombien de lignes ai-je écrites ?"` → **un seul** message envoyé dans Gemini (vérifier dans la fenêtre Chrome), réponse « 3 ».
4. Fermer complètement la fenêtre Chrome dédiée, relancer l'essai 1 → Chrome se rouvre (toujours connecté) et la réponse arrive.

- [ ] **Step 5 : Commit**

```bash
git add pilote/gemini.py pilote/essai.py
git commit -m "feat: pilote Gemini (envoi, attente, lecture) et script d'essai"
git push
```

---

## Phase 2 — Agent First

### Task 5 : Mémoire des conversations

**Files :**
- Create : `agent_first/__init__.py` (vide), `agent_first/conversations.py`
- Test : `tests/test_conversations.py`

**Interfaces :**
- Produces : `ConversationInconnue(KeyError)` ; `MemoireConversations(fichier: Path)` avec
  `creer() -> str`, `adresse(identifiant: str) -> str | None` (lève `ConversationInconnue`),
  `enregistrer(identifiant: str, adresse: str) -> None` (lève `ConversationInconnue`). Sûre entre fils.

- [ ] **Step 1 : Écrire les tests (ils échouent)**

`tests/test_conversations.py` :
```python
import pytest

from agent_first.conversations import ConversationInconnue, MemoireConversations


def test_nouvelle_conversation_sans_adresse(tmp_path):
    memoire = MemoireConversations(tmp_path / "conv.json")
    identifiant = memoire.creer()
    assert memoire.adresse(identifiant) is None


def test_identifiants_differents(tmp_path):
    memoire = MemoireConversations(tmp_path / "conv.json")
    assert memoire.creer() != memoire.creer()


def test_adresse_gardee_apres_redemarrage(tmp_path):
    fichier = tmp_path / "donnees" / "conv.json"
    memoire = MemoireConversations(fichier)
    identifiant = memoire.creer()
    memoire.enregistrer(identifiant, "https://gemini.google.com/app/abc")
    assert MemoireConversations(fichier).adresse(identifiant) == "https://gemini.google.com/app/abc"


def test_conversation_inconnue(tmp_path):
    memoire = MemoireConversations(tmp_path / "conv.json")
    with pytest.raises(ConversationInconnue):
        memoire.adresse("nexistepas")
    with pytest.raises(ConversationInconnue):
        memoire.enregistrer("nexistepas", "https://gemini.google.com/app/abc")


def test_fichier_corrompu_repart_de_zero(tmp_path):
    fichier = tmp_path / "conv.json"
    fichier.write_text("{ pas du json", encoding="utf-8")
    memoire = MemoireConversations(fichier)
    identifiant = memoire.creer()
    assert memoire.adresse(identifiant) is None


def test_fichier_corrompu_mis_de_cote(tmp_path):
    fichier = tmp_path / "conv.json"
    fichier.write_text("[1, 2]", encoding="utf-8")
    MemoireConversations(fichier)
    assert (tmp_path / "conv.corrompu.json").read_text(encoding="utf-8") == "[1, 2]"
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_conversations.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'agent_first'`

- [ ] **Step 3 : Écrire `agent_first/conversations.py`**

```python
"""Mémoire : identifiant de conversation local -> adresse de la conversation Gemini."""
import json
import logging
import os
import threading
import uuid
from pathlib import Path

journal = logging.getLogger(__name__)


class ConversationInconnue(KeyError):
    pass


class MemoireConversations:
    def __init__(self, fichier: Path) -> None:
        self._fichier = fichier
        self._verrou = threading.Lock()
        self._adresses: dict[str, str | None] = self._charger()

    def creer(self) -> str:
        with self._verrou:
            identifiant = uuid.uuid4().hex
            self._adresses[identifiant] = None
            self._sauver()
            return identifiant

    def adresse(self, identifiant: str) -> str | None:
        with self._verrou:
            if identifiant not in self._adresses:
                raise ConversationInconnue(identifiant)
            return self._adresses[identifiant]

    def enregistrer(self, identifiant: str, adresse: str) -> None:
        with self._verrou:
            if identifiant not in self._adresses:
                raise ConversationInconnue(identifiant)
            self._adresses[identifiant] = adresse
            self._sauver()

    def _charger(self) -> dict[str, str | None]:
        if not self._fichier.exists():
            return {}
        try:
            donnees = json.loads(self._fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            donnees = None
        if not isinstance(donnees, dict):
            mis_de_cote = self._fichier.with_name(self._fichier.stem + ".corrompu.json")
            os.replace(self._fichier, mis_de_cote)
            journal.warning("%s illisible, mis de côté dans %s", self._fichier, mis_de_cote)
            return {}
        return donnees

    def _sauver(self) -> None:
        self._fichier.parent.mkdir(parents=True, exist_ok=True)
        temporaire = self._fichier.with_suffix(".tmp")
        temporaire.write_text(json.dumps(self._adresses, indent=2), encoding="utf-8")
        os.replace(temporaire, self._fichier)
```

- [ ] **Step 4 : Vérifier qu'ils passent**

Run : `.venv\Scripts\python -m pytest tests/test_conversations.py -v`
Expected : 6 passed

- [ ] **Step 5 : Commit**

```bash
git add agent_first/__init__.py agent_first/conversations.py tests/test_conversations.py
git commit -m "feat: mémoire des conversations d'Agent First"
git push
```

---

### Task 6 : File d'attente (un message à la fois)

**Files :**
- Create : `agent_first/file_attente.py`
- Test : `tests/test_file_attente.py`

**Interfaces :**
- Consumes : protocole `Pilote` (tâche 1)
- Produces : `FileAttente(fabrique_pilote: Callable[[], Pilote])` avec `demarrer()`, `arreter()`,
  `soumettre(travail: Callable[[Pilote], T]) -> concurrent.futures.Future[T]`.
  Le pilote est fabriqué au premier travail, dans le fil `file-gemini`, et réutilisé ensuite.

- [ ] **Step 1 : Écrire les tests (ils échouent)**

`tests/test_file_attente.py` :
```python
import threading
import time

import pytest

from agent_first.file_attente import FileAttente
from pilote.erreurs import PasConnecteGoogle


class FauxPilote:
    def __init__(self) -> None:
        self.en_cours = 0
        self.max_en_meme_temps = 0
        self.verrou = threading.Lock()

    def travailler(self, duree: float) -> str:
        with self.verrou:
            self.en_cours += 1
            self.max_en_meme_temps = max(self.max_en_meme_temps, self.en_cours)
        time.sleep(duree)
        with self.verrou:
            self.en_cours -= 1
        return "fait"


@pytest.fixture
def fabrique():
    appels = []

    def fabriquer():
        appels.append(threading.current_thread().name)
        return FauxPilote()

    fabriquer.appels = appels
    return fabriquer


@pytest.fixture
def file(fabrique):
    f = FileAttente(fabrique)
    f.demarrer()
    yield f
    f.arreter()


def test_renvoie_le_resultat(file):
    assert file.soumettre(lambda p: p.travailler(0)).result(timeout=5) == "fait"


def test_un_seul_message_a_la_fois(file):
    futurs = [file.soumettre(lambda p: p.travailler(0.05)) for _ in range(4)]
    pilotes = [f.result(timeout=5) for f in futurs]
    assert pilotes == ["fait"] * 4
    assert file.soumettre(lambda p: p.max_en_meme_temps).result(timeout=5) == 1


def test_pilote_fabrique_une_fois_dans_le_fil_de_la_file(file, fabrique):
    file.soumettre(lambda p: p.travailler(0)).result(timeout=5)
    file.soumettre(lambda p: p.travailler(0)).result(timeout=5)
    assert fabrique.appels == ["file-gemini"]


def test_erreur_transmise_et_file_continue(file):
    def echoue(_pilote):
        raise PasConnecteGoogle()

    with pytest.raises(PasConnecteGoogle):
        file.soumettre(echoue).result(timeout=5)
    assert file.soumettre(lambda p: p.travailler(0)).result(timeout=5) == "fait"
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_file_attente.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'agent_first.file_attente'`

- [ ] **Step 3 : Écrire `agent_first/file_attente.py`**

```python
"""Un seul Chrome : les demandes passent une par une, dans un fil dédié.

Playwright (mode synchrone) doit être utilisé depuis le fil qui l'a créé :
le pilote est donc fabriqué et utilisé uniquement dans le fil de la file.
"""
import logging
import queue
import threading
from concurrent.futures import Future
from typing import Callable, TypeVar

from pilote.erreurs import ErreurPilote
from pilote.modeles import Pilote

T = TypeVar("T")
journal = logging.getLogger(__name__)
_FIN = object()


class FileAttente:
    def __init__(self, fabrique_pilote: Callable[[], Pilote]) -> None:
        self._fabrique = fabrique_pilote
        self._pilote: Pilote | None = None
        self._taches: queue.Queue = queue.Queue()
        self._fil = threading.Thread(target=self._boucle, name="file-gemini", daemon=True)

    def demarrer(self) -> None:
        self._fil.start()

    def arreter(self) -> None:
        self._taches.put(_FIN)
        self._fil.join(timeout=10)

    def soumettre(self, travail: Callable[[Pilote], T]) -> "Future[T]":
        futur: Future = Future()
        self._taches.put((travail, futur))
        return futur

    def _boucle(self) -> None:
        while True:
            element = self._taches.get()
            if element is _FIN:
                return
            travail, futur = element
            if not futur.set_running_or_notify_cancel():
                continue
            try:
                if self._pilote is None:
                    self._pilote = self._fabrique()
                futur.set_result(travail(self._pilote))
            except ErreurPilote as e:
                journal.warning("Demande à Gemini échouée : %s", e)
                futur.set_exception(e)
            except Exception as e:
                journal.exception("Erreur inattendue dans la file d'attente")
                futur.set_exception(e)
```

- [ ] **Step 4 : Vérifier qu'ils passent**

Run : `.venv\Scripts\python -m pytest tests/test_file_attente.py -v`
Expected : 4 passed

- [ ] **Step 5 : Commit**

```bash
git add agent_first/file_attente.py tests/test_file_attente.py
git commit -m "feat: file d'attente d'Agent First (un message à la fois)"
git push
```

---

### Task 7 : Serveur HTTP d'Agent First + lancement

**Files :**
- Create : `agent_first/serveur.py`, `agent_first/__main__.py`
- Test : `tests/test_serveur.py`

**Interfaces :**
- Consumes : `FileAttente`, `MemoireConversations`, `ConversationInconnue`, `ErreurPilote`, `ResultatGemini`, `ChromeDedie.est_lance`, `PiloteGemini`
- Produces : `creer_app(file, memoire, delai: float, chrome_lance: Callable[[], bool]) -> FastAPI` avec :
  - `POST /conversations` → `200 {"conversation": str}`
  - `POST /message` `{"conversation": str, "texte": str}` → `200 {"conversation", "reponse"}` ;
    erreurs `{"erreur": str}` : 422 (message vide), 404 (conversation inconnue), 502 (erreur pilote), 504 (délai), 500 (inattendu)
  - `GET /etat` → `200 {"agent_first": true, "chrome": bool, "google": bool | null}`
  - Lancement : `python -m agent_first`

- [ ] **Step 1 : Écrire les tests (ils échouent)**

`tests/test_serveur.py` :
```python
import time

import pytest
from fastapi.testclient import TestClient

from agent_first.conversations import MemoireConversations
from agent_first.file_attente import FileAttente
from agent_first.serveur import creer_app
from pilote.erreurs import PasConnecteGoogle
from pilote.modeles import ResultatGemini


class FauxPilote:
    def __init__(self) -> None:
        self.recus: list[tuple[str | None, str]] = []
        self.erreur: Exception | None = None
        self.duree = 0.0

    def envoyer(self, adresse, texte):
        self.recus.append((adresse, texte))
        time.sleep(self.duree)
        if self.erreur:
            raise self.erreur
        return ResultatGemini(reponse=f"écho : {texte}", adresse="https://gemini.google.com/app/1")

    def est_connecte(self):
        return True


@pytest.fixture
def pilote():
    return FauxPilote()


@pytest.fixture
def client(pilote, tmp_path):
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, MemoireConversations(tmp_path / "conv.json"), delai=2.0, chrome_lance=lambda: True)
    yield TestClient(app)
    file.arreter()


def nouvelle(client) -> str:
    return client.post("/conversations").json()["conversation"]


def test_premier_message_puis_suite(client, pilote):
    conv = nouvelle(client)
    r1 = client.post("/message", json={"conversation": conv, "texte": "Bonjour"})
    assert r1.status_code == 200
    assert r1.json() == {"conversation": conv, "reponse": "écho : Bonjour"}
    client.post("/message", json={"conversation": conv, "texte": "Et toi ?"})
    assert pilote.recus == [(None, "Bonjour"), ("https://gemini.google.com/app/1", "Et toi ?")]


def test_message_vide_refuse(client, pilote):
    conv = nouvelle(client)
    r = client.post("/message", json={"conversation": conv, "texte": "   \n "})
    assert r.status_code == 422
    assert "erreur" in r.json()
    assert pilote.recus == []


def test_conversation_inconnue(client):
    r = client.post("/message", json={"conversation": "nexistepas", "texte": "Bonjour"})
    assert r.status_code == 404
    assert "nouvelle conversation" in r.json()["erreur"]


def test_erreur_pilote_transmise(client, pilote):
    pilote.erreur = PasConnecteGoogle()
    r = client.post("/message", json={"conversation": nouvelle(client), "texte": "Bonjour"})
    assert r.status_code == 502
    assert r.json()["erreur"] == str(PasConnecteGoogle())


def test_delai_depasse(pilote, tmp_path):
    pilote.duree = 1.0
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, MemoireConversations(tmp_path / "conv.json"), delai=0.1, chrome_lance=lambda: True)
    client = TestClient(app)
    r = client.post("/message", json={"conversation": nouvelle(client), "texte": "Bonjour"})
    assert r.status_code == 504
    file.arreter()


def test_etat_chrome_ferme(pilote, tmp_path):
    file = FileAttente(lambda: pilote)
    file.demarrer()
    app = creer_app(file, MemoireConversations(tmp_path / "conv.json"), delai=2.0, chrome_lance=lambda: False)
    assert TestClient(app).get("/etat").json() == {"agent_first": True, "chrome": False, "google": None}
    file.arreter()


def test_etat_chrome_ouvert(client):
    assert client.get("/etat").json() == {"agent_first": True, "chrome": True, "google": True}
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_serveur.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'agent_first.serveur'`

- [ ] **Step 3 : Écrire `agent_first/serveur.py`**

```python
"""API HTTP locale d'Agent First (n'écoute que sur 127.0.0.1)."""
import logging
from concurrent.futures import TimeoutError as DelaiFutur
from typing import Callable

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from agent_first.conversations import ConversationInconnue, MemoireConversations
from agent_first.file_attente import FileAttente
from pilote.erreurs import ErreurPilote

journal = logging.getLogger(__name__)


class DemandeMessage(BaseModel):
    conversation: str
    texte: str

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
    memoire: MemoireConversations,
    delai: float,
    chrome_lance: Callable[[], bool],
) -> FastAPI:
    app = FastAPI(title="Agent First")

    @app.exception_handler(RequestValidationError)
    def demande_invalide(_requete, _exc):
        return erreur(422, "Message vide ou invalide.")

    @app.post("/conversations")
    def nouvelle_conversation():
        return {"conversation": memoire.creer()}

    @app.post("/message")
    def message(demande: DemandeMessage):
        try:
            adresse = memoire.adresse(demande.conversation)
        except ConversationInconnue:
            return erreur(404, "Conversation inconnue : démarre une nouvelle conversation.")
        futur = file.soumettre(lambda pilote: pilote.envoyer(adresse, demande.texte))
        try:
            resultat = futur.result(timeout=delai)
        except DelaiFutur:
            return erreur(504, f"Pas de réponse de Gemini après {delai:.0f} s.")
        except ErreurPilote as e:
            return erreur(502, str(e))
        except Exception as e:
            journal.exception("Erreur inattendue pendant l'envoi")
            return erreur(500, f"Erreur inattendue : {e}")
        memoire.enregistrer(demande.conversation, resultat.adresse)
        return {"conversation": demande.conversation, "reponse": resultat.reponse}

    @app.get("/etat")
    def etat():
        lance = chrome_lance()
        google = None
        if lance:
            try:
                google = file.soumettre(lambda pilote: pilote.est_connecte()).result(timeout=5)
            except Exception:
                google = None  # occupé ou injoignable : inconnu
        return {"agent_first": True, "chrome": lance, "google": google}

    return app
```

- [ ] **Step 4 : Vérifier qu'ils passent**

Run : `.venv\Scripts\python -m pytest tests/test_serveur.py -v`
Expected : 7 passed

- [ ] **Step 5 : Écrire `agent_first/__main__.py`**

```python
"""Lance Agent First : python -m agent_first"""
import logging

import uvicorn

import config
from agent_first.conversations import MemoireConversations
from agent_first.file_attente import FileAttente
from agent_first.serveur import creer_app
from pilote.chrome import ChromeDedie
from pilote.gemini import PiloteGemini


def main() -> None:
    config.DOSSIER_JOURNAUX.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s",
        handlers=[
            logging.FileHandler(config.DOSSIER_JOURNAUX / "agent_first.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    # est_lance() est appelé depuis les fils du serveur ; page() seulement
    # depuis le fil de la file d'attente (via le pilote).
    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)

    def fabrique_pilote() -> PiloteGemini:
        return PiloteGemini(
            chrome, config.URL_GEMINI, config.DELAI_REPONSE, config.STABILITE, config.DOSSIER_JOURNAUX
        )

    file = FileAttente(fabrique_pilote)
    file.demarrer()
    memoire = MemoireConversations(config.FICHIER_CONVERSATIONS)
    app = creer_app(file, memoire, config.DELAI_AGENT, chrome.est_lance)
    try:
        uvicorn.run(app, host=config.HOTE_AGENT, port=config.PORT_AGENT)
    finally:
        file.arreter()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6 : Vérification réelle**

1. Run : `.venv\Scripts\python -m agent_first` → `Uvicorn running on http://127.0.0.1:8765`.
2. Dans un autre terminal PowerShell :
   ```
   $c = (Invoke-RestMethod -Method Post http://127.0.0.1:8765/conversations).conversation
   Invoke-RestMethod -Method Post http://127.0.0.1:8765/message -ContentType "application/json" -Body (@{conversation=$c; texte="Réponds juste : bonjour"} | ConvertTo-Json)
   ```
   Expected : `reponse` contient la réponse de Gemini ; `donnees/conversations.json` contient l'adresse de la conversation.

- [ ] **Step 7 : Commit**

```bash
git add agent_first/serveur.py agent_first/__main__.py tests/test_serveur.py
git commit -m "feat: serveur HTTP local d'Agent First"
git push
```

---

## Phase 3 — Programme GUI

### Task 8 : Client HTTP de la fenêtre

**Files :**
- Create : `gui/__init__.py` (vide), `gui/client.py`
- Test : `tests/test_client.py`

**Interfaces :**
- Consumes : routes HTTP de la tâche 7
- Produces : `ErreurClient(Exception)` (texte à afficher tel quel) ; `ClientAgentFirst(url_base: str, delai: float, transport: httpx.BaseTransport | None = None)` avec
  `nouvelle_conversation() -> str`, `envoyer(conversation: str, texte: str) -> str`, `etat() -> dict`.

- [ ] **Step 1 : Écrire les tests (ils échouent)**

`tests/test_client.py` :
```python
import json

import httpx
import pytest

from gui.client import ClientAgentFirst, ErreurClient


def client_avec(gestionnaire) -> ClientAgentFirst:
    return ClientAgentFirst("http://agent", 300.0, transport=httpx.MockTransport(gestionnaire))


def test_envoyer_renvoie_la_reponse():
    recu = {}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        recu["chemin"] = requete.url.path
        recu["corps"] = json.loads(requete.content)
        return httpx.Response(200, json={"conversation": "c1", "reponse": "Salut !"})

    assert client_avec(gestionnaire).envoyer("c1", "Bonjour") == "Salut !"
    assert recu == {"chemin": "/message", "corps": {"conversation": "c1", "texte": "Bonjour"}}


def test_nouvelle_conversation():
    client = client_avec(lambda r: httpx.Response(200, json={"conversation": "c42"}))
    assert client.nouvelle_conversation() == "c42"


def test_erreur_d_agent_first_affichee_telle_quelle():
    client = client_avec(lambda r: httpx.Response(502, json={"erreur": "Connecte-toi à Google."}))
    with pytest.raises(ErreurClient, match="Connecte-toi à Google."):
        client.envoyer("c1", "Bonjour")


def test_agent_first_pas_demarre():
    def gestionnaire(requete):
        raise httpx.ConnectError("refusé", request=requete)

    with pytest.raises(ErreurClient, match="Agent First n'est pas démarré."):
        client_avec(gestionnaire).envoyer("c1", "Bonjour")


def test_delai_depasse():
    def gestionnaire(requete):
        raise httpx.ReadTimeout("trop long", request=requete)

    with pytest.raises(ErreurClient, match="5 minutes"):
        client_avec(gestionnaire).envoyer("c1", "Bonjour")


def test_reponse_illisible():
    client = client_avec(lambda r: httpx.Response(500, text="plantage"))
    with pytest.raises(ErreurClient, match="code 500"):
        client.envoyer("c1", "Bonjour")
```

- [ ] **Step 2 : Vérifier qu'ils échouent**

Run : `.venv\Scripts\python -m pytest tests/test_client.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'gui'`

- [ ] **Step 3 : Écrire `gui/client.py`**

```python
"""Parler à Agent First par HTTP."""
import httpx


class ErreurClient(Exception):
    """Erreur à afficher telle quelle dans la fenêtre."""


class ClientAgentFirst:
    def __init__(self, url_base: str, delai: float, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(base_url=url_base, timeout=delai, transport=transport)
        self._delai = delai

    def nouvelle_conversation(self) -> str:
        return self._appeler("POST", "/conversations")["conversation"]

    def envoyer(self, conversation: str, texte: str) -> str:
        contenu = self._appeler("POST", "/message", json={"conversation": conversation, "texte": texte})
        return contenu["reponse"]

    def etat(self) -> dict:
        return self._appeler("GET", "/etat")

    def _appeler(self, methode: str, chemin: str, **options) -> dict:
        try:
            reponse = self._http.request(methode, chemin, **options)
        except httpx.ConnectError as e:
            raise ErreurClient("Agent First n'est pas démarré.") from e
        except httpx.TimeoutException as e:
            raise ErreurClient(f"Pas de réponse d'Agent First après {self._delai / 60:.0f} minutes.") from e
        try:
            contenu = reponse.json()
        except ValueError:
            contenu = {}
        if reponse.is_error:
            raise ErreurClient(contenu.get("erreur") or f"Erreur d'Agent First (code {reponse.status_code}).")
        return contenu
```

- [ ] **Step 4 : Vérifier qu'ils passent**

Run : `.venv\Scripts\python -m pytest tests/test_client.py -v`
Expected : 6 passed

- [ ] **Step 5 : Commit**

```bash
git add gui/__init__.py gui/client.py tests/test_client.py
git commit -m "feat: client HTTP de la fenêtre vers Agent First"
git push
```

---

### Task 9 : Fenêtre GUI (thème sombre) + lanceur + essai de bout en bout

**Files :**
- Create : `gui/theme.py`, `gui/app.py`, `gui/__main__.py`, `demarrer.bat`
- Modify : `README.md`

**Interfaces :**
- Consumes : `ClientAgentFirst`, `ErreurClient` (tâche 8), `config`
- Produces : `python -m gui` ouvre la fenêtre ; `demarrer.bat` lance Agent First puis la fenêtre.

- [ ] **Step 1 : Écrire `gui/theme.py`**

```python
"""Couleurs et polices de la fenêtre : thème sombre, accent vert."""
import customtkinter as ctk

FOND = "#0d0d0f"
BARRE = "#111114"
CARTE = "#17171a"
CARTE_INTERNE = "#1e1e22"
SURVOL = "#26262b"
BORDURE = "#26262b"
TEXTE = "#f4f4f5"
TEXTE_2 = "#a1a1aa"
TEXTE_3 = "#6b6b75"
VERT = "#2fd99b"
ORANGE = "#f5b14c"
ROUGE = "#f06363"

POLICE = "Segoe UI"
POLICE_LOGO = "Consolas"


def police(taille: int, gras: bool = False, famille: str = POLICE) -> ctk.CTkFont:
    """À appeler après la création de la fenêtre (Tk doit exister)."""
    return ctk.CTkFont(family=famille, size=taille, weight="bold" if gras else "normal")
```

- [ ] **Step 2 : Écrire `gui/app.py`**

```python
"""Fenêtre de discussion avec Gemini, via Agent First (thème sombre)."""
import queue
import threading
from typing import Any, Callable

import customtkinter as ctk

from gui import theme as t
from gui.client import ClientAgentFirst, ErreurClient


class Fenetre(ctk.CTk):
    def __init__(self, client: ClientAgentFirst) -> None:
        super().__init__(fg_color=t.FOND)
        self._client = client
        self._conversation: str | None = None
        self._occupe = False
        self._resultats: queue.Queue = queue.Queue()

        self.title("agent.first · Gemini")
        self.geometry("1100x720")
        self.minsize(860, 560)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._construire_barre()
        self._construire_principal()

        self.after(100, self._relever_resultats)
        self.after(200, self._verifier_etat)

    # ---- construction ---------------------------------------------------

    def _construire_barre(self) -> None:
        barre = ctk.CTkFrame(self, width=260, fg_color=t.BARRE, corner_radius=0)
        barre.grid(row=0, column=0, sticky="nsw")
        barre.grid_propagate(False)
        barre.grid_columnconfigure(0, weight=1)

        logo = ctk.CTkFrame(barre, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="w", padx=24, pady=(28, 24))
        for morceau, couleur in (("agent", t.TEXTE), (".", t.VERT), ("first", t.TEXTE)):
            ctk.CTkLabel(
                logo, text=morceau, text_color=couleur, font=t.police(20, gras=True, famille=t.POLICE_LOGO)
            ).pack(side="left", padx=0)

        ctk.CTkButton(
            barre,
            text="+   Nouvelle conversation",
            command=self._nouvelle_conversation,
            fg_color=t.CARTE_INTERNE,
            hover_color=t.SURVOL,
            text_color=t.TEXTE,
            font=t.police(14, gras=True),
            corner_radius=12,
            height=44,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=16)

        self._titre_section(barre, "CONVERSATION").grid(row=2, column=0, sticky="w", padx=24, pady=(30, 8))
        self._libelle_conversation = ctk.CTkLabel(
            barre, text="Aucune conversation", text_color=t.TEXTE_2, font=t.police(13), anchor="w"
        )
        self._libelle_conversation.grid(row=3, column=0, sticky="ew", padx=24)

        self._titre_section(barre, "ÉTAT").grid(row=4, column=0, sticky="w", padx=24, pady=(30, 8))
        etats = ctk.CTkFrame(barre, fg_color="transparent")
        etats.grid(row=5, column=0, sticky="ew", padx=24)
        self._etat_agent = self._ligne_etat(etats)
        self._etat_chrome = self._ligne_etat(etats)
        self._etat_google = self._ligne_etat(etats)
        self._mettre_etat(self._etat_agent, "Agent First · connexion…", t.TEXTE_3)
        self._mettre_etat(self._etat_chrome, "Chrome dédié · …", t.TEXTE_3)
        self._mettre_etat(self._etat_google, "Compte Google · …", t.TEXTE_3)

    def _construire_principal(self) -> None:
        principal = ctk.CTkFrame(self, fg_color="transparent")
        principal.grid(row=0, column=1, sticky="nsew", padx=32, pady=(30, 24))
        principal.grid_columnconfigure(0, weight=1)
        principal.grid_rowconfigure(1, weight=1)

        entete = ctk.CTkFrame(principal, fg_color="transparent")
        entete.grid(row=0, column=0, pady=(0, 22))
        titre = ctk.CTkFrame(entete, fg_color="transparent")
        titre.pack()
        ctk.CTkLabel(titre, text="Discute avec ", text_color=t.TEXTE, font=t.police(28, gras=True)).pack(side="left")
        ctk.CTkLabel(titre, text="Gemini", text_color=t.VERT, font=t.police(28, gras=True)).pack(side="left")
        ctk.CTkLabel(
            entete,
            text="Tes messages passent par Agent First et le Chrome dédié.",
            text_color=t.TEXTE_2,
            font=t.police(15),
        ).pack(pady=(4, 0))

        carte = ctk.CTkFrame(principal, fg_color=t.CARTE, corner_radius=20, border_width=1, border_color=t.BORDURE)
        carte.grid(row=1, column=0, sticky="nsew")
        carte.grid_columnconfigure(0, weight=1)
        carte.grid_rowconfigure(0, weight=1)
        self._historique = ctk.CTkTextbox(
            carte,
            fg_color=t.CARTE,
            text_color=t.TEXTE,
            font=t.police(14),
            wrap="word",
            state="disabled",
            scrollbar_button_color=t.BORDURE,
            scrollbar_button_hover_color=t.SURVOL,
        )
        self._historique.grid(row=0, column=0, sticky="nsew", padx=18, pady=16)
        self._historique.tag_config("toi", foreground=t.VERT, spacing1=12)
        self._historique.tag_config("gemini", foreground=t.TEXTE_2, spacing1=12)
        self._historique.tag_config("erreur", foreground=t.ROUGE, spacing1=12)
        self._historique.tag_config("message", spacing3=6)

        saisie = ctk.CTkFrame(principal, fg_color=t.CARTE, corner_radius=28, border_width=1, border_color=t.BORDURE)
        saisie.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        saisie.grid_columnconfigure(0, weight=1)
        self._saisie = ctk.CTkTextbox(
            saisie,
            height=52,
            fg_color=t.CARTE,
            text_color=t.TEXTE,
            font=t.police(15),
            wrap="word",
            activate_scrollbars=False,
        )
        self._saisie.grid(row=0, column=0, sticky="ew", padx=(22, 8), pady=8)
        # Entrée envoie ; Maj+Entrée va à la ligne (comportement par défaut du champ).
        self._saisie.bind("<Return>", self._sur_entree)
        self._saisie.bind("<Shift-Return>", lambda _e: None)
        self._bouton_envoyer = ctk.CTkButton(
            saisie,
            text="→",
            command=self._envoyer,
            width=44,
            height=44,
            corner_radius=22,
            fg_color=t.CARTE_INTERNE,
            hover_color=t.SURVOL,
            text_color=t.TEXTE,
            font=t.police(18, gras=True),
        )
        self._bouton_envoyer.grid(row=0, column=1, padx=(0, 8), pady=8)

        pied = ctk.CTkFrame(principal, fg_color="transparent")
        pied.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        pied.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            pied,
            text="Entrée pour envoyer · Maj+Entrée pour aller à la ligne",
            text_color=t.TEXTE_3,
            font=t.police(12),
        ).grid(row=0, column=0, sticky="w", padx=10)
        pastille = ctk.CTkFrame(pied, fg_color=t.TEXTE, corner_radius=18)
        pastille.grid(row=0, column=1, sticky="e")
        self._texte_pastille = ctk.CTkLabel(
            pastille, text="Connexion…", text_color=t.FOND, font=t.police(13, gras=True)
        )
        self._texte_pastille.pack(side="left", padx=(16, 8), pady=6)
        self._point_pastille = ctk.CTkFrame(pastille, width=8, height=8, corner_radius=4, fg_color=t.TEXTE_3)
        self._point_pastille.pack(side="left", padx=(0, 16))

    def _titre_section(self, parent: ctk.CTkFrame, texte: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=texte, text_color=t.TEXTE_3, font=t.police(12, gras=True))

    def _ligne_etat(self, parent: ctk.CTkFrame) -> tuple[ctk.CTkFrame, ctk.CTkLabel]:
        ligne = ctk.CTkFrame(parent, fg_color="transparent")
        ligne.pack(fill="x", pady=5)
        point = ctk.CTkFrame(ligne, width=8, height=8, corner_radius=4, fg_color=t.TEXTE_3)
        point.pack(side="left", padx=(0, 10))
        etiquette = ctk.CTkLabel(ligne, text="", text_color=t.TEXTE_2, font=t.police(13), anchor="w")
        etiquette.pack(side="left", fill="x", expand=True)
        return point, etiquette

    # ---- actions --------------------------------------------------------

    def _sur_entree(self, _evenement) -> str:
        self._envoyer()
        return "break"

    def _envoyer(self) -> None:
        texte = self._saisie.get("1.0", "end").strip()
        if not texte or self._occupe:
            return
        self._saisie.delete("1.0", "end")
        if self._conversation is None:
            self._libelle_conversation.configure(text=texte if len(texte) <= 28 else texte[:27] + "…")
        self._ajouter("Toi", texte, "toi")
        self._occuper(True)
        conversation = self._conversation

        def travail() -> tuple[str, str]:
            identifiant = conversation or self._client.nouvelle_conversation()
            return identifiant, self._client.envoyer(identifiant, texte)

        def quand_fini(resultat: tuple[str, str] | None, erreur: str | None) -> None:
            self._occuper(False)
            if erreur:
                self._ajouter("Erreur", erreur, "erreur")
                self._signaler("Erreur", t.ROUGE)
                self._saisie.insert("1.0", texte)  # pour pouvoir le renvoyer
                return
            self._conversation, reponse = resultat
            self._ajouter("Gemini", reponse, "gemini")
            self._mettre_etat(self._etat_chrome, "Chrome dédié · ouvert", t.VERT)
            self._mettre_etat(self._etat_google, "Compte Google · connecté", t.VERT)

        self._lancer(travail, quand_fini)

    def _nouvelle_conversation(self) -> None:
        if self._occupe:
            return
        self._conversation = None
        self._libelle_conversation.configure(text="Nouvelle conversation")
        self._historique.configure(state="normal")
        self._historique.delete("1.0", "end")
        self._historique.configure(state="disabled")
        self._saisie.focus_set()

    def _verifier_etat(self) -> None:
        def quand_fini(etat: dict | None, erreur: str | None) -> None:
            if erreur:
                self._mettre_etat(self._etat_agent, "Agent First · pas démarré", t.ROUGE)
                self._signaler("Agent First arrêté", t.ROUGE)
                self.after(3000, self._verifier_etat)
                return
            self._mettre_etat(self._etat_agent, "Agent First · prêt", t.VERT)
            if etat["chrome"]:
                self._mettre_etat(self._etat_chrome, "Chrome dédié · ouvert", t.VERT)
            else:
                self._mettre_etat(self._etat_chrome, "Chrome dédié · au 1er message", t.TEXTE_3)
            google = {
                True: ("connecté", t.VERT),
                False: ("non connecté", t.ROUGE),
                None: ("à vérifier", t.TEXTE_3),
            }[etat["google"]]
            self._mettre_etat(self._etat_google, f"Compte Google · {google[0]}", google[1])
            if not self._occupe:
                self._signaler("Prêt", t.VERT)

        self._lancer(self._client.etat, quand_fini)

    # ---- outils ---------------------------------------------------------

    def _lancer(self, travail: Callable[[], Any], quand_fini: Callable[[Any, str | None], None]) -> None:
        """Exécute `travail` hors du fil de la fenêtre ; `quand_fini(resultat, erreur)`
        est ensuite appelé dans le fil de la fenêtre."""

        def fil() -> None:
            try:
                self._resultats.put((quand_fini, travail(), None))
            except ErreurClient as e:
                self._resultats.put((quand_fini, None, str(e)))

        threading.Thread(target=fil, daemon=True).start()

    def _relever_resultats(self) -> None:
        while True:
            try:
                quand_fini, resultat, erreur = self._resultats.get_nowait()
            except queue.Empty:
                break
            quand_fini(resultat, erreur)
        self.after(100, self._relever_resultats)

    def _occuper(self, occupe: bool) -> None:
        self._occupe = occupe
        self._bouton_envoyer.configure(state="disabled" if occupe else "normal")
        if occupe:
            self._signaler("Gemini écrit…", t.ORANGE)
        else:
            self._signaler("Prêt", t.VERT)

    def _signaler(self, texte: str, couleur: str) -> None:
        self._texte_pastille.configure(text=texte)
        self._point_pastille.configure(fg_color=couleur)

    def _mettre_etat(self, ligne: tuple[ctk.CTkFrame, ctk.CTkLabel], texte: str, couleur: str) -> None:
        point, etiquette = ligne
        point.configure(fg_color=couleur)
        etiquette.configure(text=texte)

    def _ajouter(self, auteur: str, texte: str, tag: str) -> None:
        self._historique.configure(state="normal")
        self._historique.insert("end", f"{auteur}\n", tag)
        self._historique.insert("end", f"{texte}\n", "message")
        self._historique.configure(state="disabled")
        self._historique.see("end")
```

- [ ] **Step 3 : Écrire `gui/__main__.py`**

```python
"""Lance la fenêtre : python -m gui"""
import customtkinter as ctk

import config
from gui.app import Fenetre
from gui.client import ClientAgentFirst


def main() -> None:
    ctk.set_appearance_mode("dark")
    client = ClientAgentFirst(f"http://{config.HOTE_AGENT}:{config.PORT_AGENT}", config.DELAI_GUI)
    Fenetre(client).mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4 : Écrire `demarrer.bat` et compléter `README.md`**

`demarrer.bat` :
```bat
@echo off
cd /d "%~dp0"
start "Agent First" .venv\Scripts\python.exe -m agent_first
start "" .venv\Scripts\pythonw.exe -m gui
```

`README.md` :
````markdown
# gemini-in-to-agent-first

Discuter avec Gemini (site web) depuis une fenêtre sur mesure : la fenêtre
envoie le message à **Agent First**, qui pilote un Chrome dédié connecté à
Google, lit la réponse et la renvoie.

## Installation (une fois)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Au premier lancement, une fenêtre Chrome séparée s'ouvre sur Gemini :
connecte-toi à ton compte Google dedans (une seule fois).

## Utilisation

Double-clique `demarrer.bat`.

## Tests

```
.venv\Scripts\python -m pytest
```

Conception : `docs/superpowers/specs/` · Plan : `docs/superpowers/plans/`
````

- [ ] **Step 5 : Tous les tests automatiques**

Run : `.venv\Scripts\python -m pytest -v`
Expected : 31 passed

- [ ] **Step 6 : Essai de bout en bout (les 4 critères de la fiche + le style)**

Double-cliquer `demarrer.bat` :
1. Fenêtre sombre comme l'image de référence : barre latérale avec `agent.first` (point vert), titre « Discute avec Gemini », pastille blanche « Prêt ● » en bas à droite, section ÉTAT avec Agent First en vert.
2. Taper « Bonjour » + Entrée → pastille « Gemini écrit… » orange, puis la réponse de Gemini s'affiche et la pastille repasse à « Prêt ».
3. « Quel mot t'ai-je écrit ? » → Gemini répond « Bonjour » (même conversation).
4. « Nouvelle conversation » puis « Quel mot t'ai-je écrit ? » → Gemini ne sait pas (conversation vide).
5. Fermer la console « Agent First », envoyer un message → « Agent First n'est pas démarré. » en rouge, et le message revient dans le champ de saisie.
6. Maj+Entrée dans le champ → va à la ligne sans envoyer ; le message multi-lignes part en un seul bloc.

- [ ] **Step 7 : Commit**

```bash
git add gui/theme.py gui/app.py gui/__main__.py demarrer.bat README.md
git commit -m "feat: fenêtre GUI au thème sombre et lanceur"
git push
```
