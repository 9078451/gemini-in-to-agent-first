# Rapidité, interface épurée, autres fournisseurs — plan

> **Pour les agents :** exécuté en natif (superpowers:executing-plans), tâche par tâche.

**But :** réponses au fil de l'eau, app qui ne se fige plus, interface affinée,
fournisseurs par clé API et sites ChatGPT / Claude.ai, avec secours automatique.

**Architecture :** chaque fournisseur est un `Pilote` (même contrat que Gemini) ;
un `Repartiteur` donne la file de chaque fournisseur ; `ServiceChat` envoie un
message (historique à plat si le fournisseur change, secours, états).

**Technique :** Python 3.13, FastAPI, Playwright (CDP), httpx, SDK `anthropic`,
`markdown-it-py`, nh3 ; JavaScript en modules ES sans outil de construction.

**Fiche :** `docs/superpowers/specs/2026-10-19-rapidite-gui-fournisseurs-design.md`

## Contraintes globales

- Textes de l'app en français ; style : gris chauds, accent unique `#d97757`.
- Tests : `.venv\Scripts\python -m pytest` et `node --test tests/web/*.test.mjs`
  (venv du dossier principal) ; chaque tâche finit tests verts, commit, push main.
- Ne jamais commiter `style to copy.png`, `donnees/`, `journaux/`, `profil-chrome-gemini/`.
- Une clé API ne repart jamais vers la page (seulement `••••` + 4 derniers caractères).

## Points d'attention (testés dans la tâche qui les porte)

1. Une conversation supprimée pendant une réponse en flux : la réponse est perdue
   sans erreur 500 (tâche 2).
2. Arrêter juste avant la fin : rien n'est enregistré deux fois (tâche 2).
3. Secours vers le même fournisseur que celui en panne : pas de boucle (tâche 5).
4. Changer de fournisseur au milieu d'une conversation : le nouveau reçoit
   l'historique à plat, une seule fois (tâche 5).
5. Flux HTTP d'une API coupé au milieu : erreur claire, texte partiel gardé, pas
   de nouvel essai (tâche 4).

---

### Tâche 1 : base et serveur plus solides

**Fichiers :** `agent_first/historique.py`, `agent_first/serveur.py`,
`agent_first/api_reseau.py`, `tests/test_historique.py`, `tests/test_serveur.py`

- [ ] Test : `Historique` ouvre la base en WAL (`PRAGMA journal_mode` → `wal`).
- [ ] Colonnes `conversations.fournisseur TEXT NOT NULL DEFAULT 'gemini'` et
      `messages.fournisseur TEXT`, migrées ; `ajouter_message(..., fournisseur=None)`,
      `creer(..., fournisseur="gemini")`, `changer_fournisseur(id, fournisseur, modele, niveau)`
      (adresse remise à NULL, tours à 0) ; `renommer(id, titre)`.
- [ ] Limite d'anyio à 200 au démarrage (lifespan) des deux apps.
- [ ] `/api/etat` : état de Google gardé (`EtatGoogle`) ; relu dans la file du Chat
      seulement si elle est libre et l'état vieux de plus de 60 s. Test : file occupée
      → réponse immédiate avec l'ancien état.
- [ ] `PATCH /api/conversations/{id}` `{titre}`.
- [ ] Tests verts ; commit.

### Tâche 2 : réponses au fil de l'eau (Gemini) et Arrêter

**Fichiers :** `pilote/sonde.py` (nouveau), `pilote/attente.py`, `pilote/gemini.py`,
`pilote/erreurs.py` (`Interrompu(partiel)`), `pilote/modeles.py`, `agent_first/serveur.py`,
`tests/test_attente.py`, `tests/test_sonde.py`, `tests/test_serveur.py`

**Interfaces produites :**
- `Pilote.envoyer(adresse, texte, modele=None, niveau=None, delai=None, au_fil=None)` ;
  `au_fil(texte: str, html: str) -> None`.
- `attendre_fin_reponse(..., au_fil: Callable[[str], None] | None = None)` appelle
  `au_fil(texte)` à chaque changement.
- `Sonde(page, selecteurs).lire() -> dict` (`questions, reponses, generation, limite, texte, html`).

- [ ] Tests `attente` : `au_fil` reçoit chaque texte nouveau ; une exception levée par
      `au_fil` remonte.
- [ ] `Sonde` : un seul `page.evaluate` par lecture, cache 50 ms (horloge injectée).
- [ ] `PiloteGemini` utilise la sonde dans ses attentes ; `au_fil` reçoit texte + HTML
      partiel ; `Interrompu` → clic sur « Interrompre la réponse » puis l'erreur remonte.
- [ ] Serveur : `?flux=1` → NDJSON (`partiel` au plus toutes les 150 ms, puis `message`
      ou `erreur`) ; `POST /api/conversations/{id}/arreter`. Interrompu : la réponse
      partielle est enregistrée avec la note « interrompue ». Tests avec faux pilote.
- [ ] Commit et push.

### Tâche 3 : fournisseurs — catalogue, réglages, répartiteur

**Fichiers :** `fournisseurs/__init__.py`, `fournisseurs/catalogue.py`,
`fournisseurs/reglages.py`, `fournisseurs/repartiteur.py`, `fournisseurs/etats.py`,
`tests/test_fournisseurs.py`

**Interfaces produites :**
- `CATALOGUE: dict[str, Fournisseur]` ; `Fournisseur(id, nom, type: "web"|"api",
  base_url, cle_requise, effort, modeles_suggeres, aide)`.
- `ReglagesFournisseurs(fichier)` : `lire() -> dict`, `cle(id) -> str|None`,
  `enregistrer(id, cle=None, actif=None, modeles=None, url=None)`, `secours() -> dict`,
  `regler_secours(actif, fournisseur, modele)`, `publics() -> list[dict]` (clé masquée).
- `Repartiteur(fabriques: dict[str, Callable[[str], Pilote]], paralleles: set[str])` :
  `file(fournisseur, role) -> FileAttente|FileParallele` (créée au premier besoin),
  `arreter()`.
- `EtatsFournisseurs` : `noter_ok(id)`, `noter_erreur(id, erreur)`, `tous() -> dict`.

- [ ] Tests : clé masquée ; fichier absent ou abîmé → réglages vides ; une file par
      (fournisseur, rôle), créée une fois ; `FileParallele` exécute deux travaux en même
      temps ; état « limite » noté depuis `LimiteGemini`.
- [ ] Commit.

### Tâche 4 : pilotes par clé API

**Fichiers :** `fournisseurs/memoire.py`, `fournisseurs/api_openai.py`,
`fournisseurs/api_anthropic.py`, `fournisseurs/markdown.py`, `pilote/erreurs.py`
(`CleRefusee`, `LimiteFournisseur`, `FournisseurIndisponible`, attribut `secours`),
`requirements.txt` (+ `anthropic>=1.15`, `markdown-it-py>=4`), `tests/test_api_openai.py`,
`tests/test_api_anthropic.py`

- [ ] `MemoireFils(fichier)` : `lire(adresse) -> list[dict]`, `ecrire(adresse, messages)`.
- [ ] `PiloteOpenAI(fournisseur, cle, base_url, memoire, client=None)` : flux SSE
      (`httpx.MockTransport` dans les tests) ; `au_fil` à chaque morceau ; 401/403 →
      `CleRefusee` ; 429 → reprise puis `LimiteFournisseur` ; coupure après un morceau →
      `FournisseurIndisponible` avec le partiel, sans reprise ; `lister_modes()` filtré.
- [ ] `PiloteClaudeAPI(cle, memoire, client=None)` : SDK `anthropic`, `messages.stream`,
      effort selon le niveau, refus → message clair. Tests avec un faux client.
- [ ] Réponse Markdown → HTML (`markdown-it-py`) → nh3.
- [ ] Commit et push.

### Tâche 5 : ServiceChat, secours, branchement partout

**Fichiers :** `agent_first/discussion.py` (nouveau), `agent_first/assemblage.py`,
`agent_first/serveur.py`, `agent_first/api_reseau.py`, `agent_first/cowork_service.py`,
`agent_first/__main__.py`, `tests/test_discussion.py`, tests existants adaptés

**Interfaces produites :**
- `ServiceChat.envoyer(conversation_id, texte, fournisseur, modele, niveau, au_fil=None,
  arret=None, texte_pilote=None) -> Message`.
- Routes : `GET /api/fournisseurs`, `PUT /api/fournisseurs/{id}`,
  `POST /api/fournisseurs/{id}/modeles`, `PUT /api/secours`,
  `GET /api/modeles` → `{fournisseurs: [...], secours}`.
- API réseau : modèles `fournisseur/modele` (Gemini garde ses noms nus).

- [ ] Tests : changement de fournisseur → texte à plat une fois ; secours sur
      `LimiteGemini` → réponse du secours, conversation passée au secours ; secours =
      même fournisseur → pas de boucle ; Cowork continue chez le secours (évènement
      `secours`).
- [ ] Commit et push.

### Tâche 6 : interface épurée

**Fichiers :** `agent_first/web/index.html`, `app.css`, `app.js`, nouveaux
`fil.js`, `rendu_cowork.js`, `parametres.js`, `palette.js`, `outils.js`,
`tests/web/outils.test.mjs`

- [ ] Fonctions pures testées : `groupesFournisseurs`, `metaMessage` (fournisseur,
      secours), `lireNdjson` (morceaux coupés au milieu d'une ligne).
- [ ] Barre, fil, menu des modèles par fournisseur, Arrêter, notifications, Paramètres
      en onglets, palette Ctrl K, revenir en bas, reconnexion du flux Cowork.
- [ ] Essai dans le navigateur avec le faux pilote (captures), puis commit et push.

### Tâche 7 : sites ChatGPT et Claude.ai

**Fichiers :** `pilote/chrome.py` (onglet générique `OngletSite`), `pilote/site.py`,
`pilote/sites.py`, `pilote/inspecter.py`, `tests/test_site.py`, `tests/test_chrome.py`

- [ ] `choisir_onglet(onglets, role, principal, prefixe)` ; `OngletGemini` = cas de
      `OngletSite`.
- [ ] `PiloteSite(onglet, profil, …)` : nouvelle conversation, envoi, attente avec la
      sonde du profil, connexion vérifiée, `au_fil`, `Interrompu`.
- [ ] Profils `CHATGPT` et `CLAUDE_WEB` (repères relevés dans la page).
- [ ] README (fournisseurs, secours, avertissement des sites), commit et push.
