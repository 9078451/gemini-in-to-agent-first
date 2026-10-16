# agent.first v3 — plan de réalisation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Gemini reste un agent Cowork qui agit, vérifie et ne finit pas trop tôt, avec un protocole anglais plus puissant (lots, processus, visite), un fil plus lisible, et une API réseau (format OpenAI + Cowork) protégée par clé.

**Architecture :** le catalogue des actions (`cowork/catalogue.py`) est la source unique du protocole ; `format` lit les lots, `instructions` construit le cadre envoyé à chaque demande, `actions`/`processus`/`visite` exécutent sans jamais lever, `tache` + `boucle` enchaînent lots, plan et fin contrôlée. Le service Cowork garde un journal rejouable par tâche, les processus par conversation et publie sur un diffuseur global. Un second serveur FastAPI (port 8766, 0.0.0.0) expose `/v1` derrière une clé.

**Tech Stack :** Python 3.12, FastAPI 0.143, uvicorn 0.54, Playwright (inchangé), SQLite, JS natif (modules ES), pytest, `node --test`.

**Spec :** `docs/superpowers/specs/2026-10-16-agent-first-v3-design.md`

## Global Constraints

- Code, noms et commentaires en français (convention du projet) ; **protocole avec Gemini et API `/v1` en anglais** ; l'utilisateur lit du français dans l'app.
- Actions : `list read search create edit delete run start logs stop visit plan ask done` ; champs `path content old new command pattern glob id url method body steps question summary`.
- Alias acceptés : `lister→list lire→read chercher→search creer→create modifier→edit supprimer→delete commande→run` ; `chemin→path contenu→content avant→old apres→new texte→command motif→pattern`.
- Valeurs de `config.py` : `MAX_TOURS_COWORK = 40`, `MAX_ACTIONS_PAR_MESSAGE = 10`, `RELANCES_FIN_MAX = 2`, `MAX_PROCESSUS = 3`, `ATTENTE_DEMARRAGE = 3.0`, `DELAI_VISITE = 10.0`, `MAX_ENTREES_ARBORESCENCE = 150`, `TAILLE_MAX_MESSAGE = 30000`, `API_ACTIVE = True`, `HOTE_API = "0.0.0.0"`, `PORT_API = 8766`, `FICHIER_CLE_API = DOSSIER_DONNEES / "cle_api.txt"`, `ESSAIS_CLE_MAX = 10` (par 60 s, blocage 60 s). `MAX_ETAPES_COWORK` est renommé `MAX_TOURS_COWORK`.
- Ports interdits à `visit` : `PORT_AGENT`, `PORT_API`, `PORT_CHROME`.
- Dossiers ignorés par l'arborescence : `.git node_modules __pycache__ .venv venv`.
- Tout résultat d'action est un `Resultat` ; aucune exception ne sort de `Executeur.executer`.
- Ne jamais commiter `style to copy.png`, `donnees/`, `journaux/`, `profil-chrome-gemini/`. Commit à la fin de chaque tâche ; push sur `main` à la fin.
- Tests : `.venv\Scripts\python -m pytest` et `node --test tests/web/` doivent passer à chaque commit.

## Review Focus

1. **Texte réel de Gemini web** : préfixe « Gemini a dit », bloc affiché « JSON » sans ```` ``` ````, liste d'actions, prose autour → toutes les actions lues dans l'ordre (test Tâche 1 `test_liste_affichee_par_gemini_web`).
2. **« TERMINÉ » ou `"done"` à l'intérieur d'un contenu de fichier** ne doit jamais finir la tâche (test Tâche 1 `test_termine_dans_un_contenu_n_est_pas_une_fin`).
3. **Chemins Windows** `app\\views\\x.html` et `app/views/x.html` → même fichier, dans le dossier ; `C:\\autre` et `..\\x` → refus (test Tâche 3 `test_chemins_windows`).
4. **Serveur muet qui tourne** (`python -c` qui dort sans rien écrire) → `started #1` avec « (no output yet) » en ~3 s, sans blocage ; `arreter_tout()` le tue (test Tâche 4 `test_processus_muet_ne_bloque_pas`).
5. **Ancienne conversation** (noms français dans l'historique et chez Gemini) : alias lus (Tâche 1) et étapes affichées (Tâche 8 `libelleEtape ancien nom`).

---

### Tâche 1 : catalogue des actions et lecture des lots

**Files :**
- Create : `cowork/catalogue.py`, `tests/test_catalogue.py`
- Modify : `cowork/format.py` (réécrit), `tests/test_format.py` (réécrit)

**Interfaces :**
- Produces (`cowork/catalogue.py`) :
  - `@dataclass(frozen=True) class Definition: nom: str; requis: tuple[str, ...]; optionnels: tuple[str, ...]; aide: str; exemple: dict; ancien_nom: str | None = None`
  - `CATALOGUE: dict[str, Definition]` (ordre = ordre d'affichage) ; `ALIAS_CHAMPS: dict[str, str]`
  - `CLES: tuple[str, ...]` (tous les champs, anglais + alias, + `"action"`)
  - `normaliser(objet: dict) -> Action | None` : nom/champs alias → anglais ; scalaires → `str` ; listes gardées (`steps`) ; `None` si pas de clé `action` texte.
  - `valider(action: Action) -> str | None` : `'unknown action "x" (known: list, read, …)'` ou `'missing field "path"'`.
  - `resume_action(action: Action) -> str` : `create index.html`, `run "python x.py"`, `visit http://localhost:8080/`, `plan`, `stop #1`.
  - `liste_compacte() -> str` : une ligne par action `name  {exemple JSON}  aide`.
- Produces (`cowork/format.py`) :
  - `@dataclass(frozen=True) class Action: nom: str; champs: dict` (déplacée ici inchangée de nom ; `champs` peut contenir une liste)
  - `lire_actions(message: str) -> list[Action]` ; `[]` si rien.
  - `@dataclass(frozen=True) class LigneResultat: rang: int; action: Action; statut: str; corps: str` (`statut` ∈ `"OK"`, `"ERROR"`, `"SKIPPED"`, ou `"ERROR (exit code N)"`)
  - `formater_resultats(lignes: list[LigneResultat], taille_max: int, taille_max_message: int, note: str = "") -> str`
  - `rappel_pour(message: str) -> str`, `est_erreur_gemini(message: str) -> bool` (gardée), `PIED: str`
  - Supprimées : `lire_action`, `est_termine`, `formater_resultat`.

- [ ] **Étape 1 : écrire les tests qui échouent**

`tests/test_catalogue.py` :
- `test_alias_francais_normalises` : `normaliser({"action":"creer","chemin":"a","contenu":"x"}) == Action("create", {"path":"a","content":"x"})`.
- `test_steps_reste_une_liste` : `normaliser({"action":"plan","steps":["[ ] a"]}).champs["steps"] == ["[ ] a"]`.
- `test_nombre_devient_texte` : `normaliser({"action":"stop","id":1}).champs["id"] == "1"`.
- `test_valider_champ_manquant` : `valider(Action("read", {})) == 'missing field "path"'` ; `valider(Action("list", {})) is None`.
- `test_valider_action_inconnue` : message commence par `'unknown action "fly"'` et contient `create`.
- `test_resume_action` : `resume_action(Action("run", {"command":"dir"})) == 'run "dir"'`.
- `test_liste_compacte_couvre_tout_le_catalogue` : chaque nom de `CATALOGUE` apparaît dans `liste_compacte()`.

`tests/test_format.py` (on garde les cas réels existants, adaptés) :
- `test_un_bloc_une_action`, `test_plusieurs_blocs_dans_l_ordre`, `test_liste_dans_un_bloc` (`[{"action":"read",...},{"action":"list"}]` → 2 actions).
- `test_liste_affichee_par_gemini_web` : `'Gemini a dit\nJe commence.\nJSON\n[\n {"action": "plan", "steps": ["[ ] lire"]},\n {"action": "list", "path": "."}\n]'` → `["plan", "list"]`.
- `test_objet_affiche_sans_backticks` (ex-`test_lire_action_dans_le_texte_affiche_par_gemini`, `contenu` `"x { y }"` gardé).
- `test_reparer_guillemets_non_echappes` (cas réel existant, avec `"action": "modifier"` → `Action("edit", {"path":…, "old":…, "new":…})`) et `test_reparer_avec_cles_anglaises`.
- `test_termine_francais_vaut_done` : `"TERMINÉ : fini"` → `[Action("done", {"summary": "fini"})]`.
- `test_termine_dans_un_contenu_n_est_pas_une_fin` : un `create` dont `content` vaut `"TERMINÉ"` → une seule action `create`.
- `test_rien_a_lire` : `"je réfléchis"` → `[]` ; `'{"nom": "x"}'` → `[]`.
- `test_formater_resultats` : 3 lignes OK/ERROR (exit code 1)/SKIPPED → commence par `"RESULTS\n[1] create a.txt: OK\n"`, contient `"[3] create b.txt: SKIPPED"`, finit par `PIED`.
- `test_resultat_coupe` : corps de 50 car., `taille_max=10` → contient `"…(cut)"`.
- `test_rappel_json_abime` / `test_rappel_general` : `rappel_pour('{"action": "x", oups')` contient `\\"` ; le rappel général contient `liste_compacte()`.
- `test_erreur_gemini` (gardé).

- [ ] **Étape 2 : lancer, constater l'échec**

Run : `.venv\Scripts\python -m pytest tests/test_catalogue.py tests/test_format.py -q` → FAIL (import).

- [ ] **Étape 3 : écrire `cowork/catalogue.py` puis réécrire `cowork/format.py`**

Lecture (`lire_actions`) : (1) chaque bloc ```` ```json ```` décodé (objet ou liste) ; (2) si aucun bloc n'a donné d'action, balayage du texte : à chaque `{` ou `[`, `json.JSONDecoder().raw_decode` ; un objet/liste décodé contenant des actions est pris et la lecture **reprend après sa fin** (les accolades d'un contenu ne sont jamais relues) ; (3) sinon `_reparer` (existant, clés = `CLES`) ; (4) sinon, si `"TERMINÉ"` est dans le texte : `done` avec le texte après `TERMINÉ` (sans `:`). Chaque objet passe par `normaliser`. `PIED` = `'Reply with JSON actions only. Finish with {"action": "done", "summary": "…"} once every plan step is [x] and verified.'`. Coupe : `"\n…(cut)"`. Message total coupé à `taille_max_message`.

- [ ] **Étape 4 : tests au vert**, puis `pytest -q` complet : les tests de `boucle`, `surete`, `actions`, `cowork_api` qui importent `lire_action`/`formater_resultat` cassent → les adapter au minimum dans les tâches 3 et 5 ; à cette étape, marquer `tests/test_boucle.py` et `tests/test_cowork_api.py` comme réécrits plus loin en ne lançant que les deux fichiers ci-dessus.

- [ ] **Étape 5 : commit** — `feat(cowork): catalogue des actions en anglais et lecture des lots`

---

### Tâche 2 : le cadre envoyé à Gemini

**Files :**
- Modify : `cowork/instructions.py` (réécrit), `tests/test_instructions.py` (réécrit)

**Interfaces :**
- Consumes : `liste_compacte()` (Tâche 1).
- Produces :
  - `arborescence(dossier: Path, max_entrees: int) -> str` : dossiers d'abord, triés, indentés de 2 espaces, `/` final pour un dossier, ignorés : liste des Global Constraints ; au-delà : `… (N more)` ; dossier vide : `(empty)`.
  - `cadre(dossier: Path, demande: str, *, contenu: str, processus: str, derniere_tache: str, reponse: bool, max_actions: int) -> str` — texte de la section 4.4 de la spec (en anglais, `[AGENT FIRST · COWORK]` … `Reply now with your first actions.`) ; `processus`/`derniere_tache` vides → lignes `RUNNING PROCESSES: none` / `LAST TASK: none` ; `reponse=True` → `USER ANSWER TO YOUR QUESTION:` au lieu de `USER REQUEST:`.

- [ ] **Étape 1 : tests**
- `test_cadre_contient_role_actions_dossier_demande` : contient `"[AGENT FIRST · COWORK]"`, chaque nom du `CATALOGUE`, `str(dossier)`, `'"""\ncrée a.txt\n"""'`, `"Never tell the user to run something"`, `"in French"`.
- `test_cadre_regle_echappement` : contient `\\"` et `\\n`.
- `test_cadre_reponse_a_une_question` : `reponse=True` → `"USER ANSWER TO YOUR QUESTION:"` et pas `"USER REQUEST:"`.
- `test_cadre_dit_que_le_dossier_est_borne` : contient `"File actions only work inside the working folder"`.
- `test_arborescence` (tmp_path : `a/b.txt`, `c.py`, `.git/x`, `node_modules/y`) → `"a/\n  b.txt\nc.py"`.
- `test_arborescence_limite` : 200 fichiers, `max_entrees=150` → finit par `"… (50 more)"`.

- [ ] **Étape 2 : échec constaté** — `pytest tests/test_instructions.py -q`
- [ ] **Étape 3 : implémenter** (`premier_message`/`mode_emploi` supprimés).
- [ ] **Étape 4 : vert.**
- [ ] **Étape 5 : commit** — `feat(cowork): cadre complet en anglais à chaque demande, avec le contenu du dossier`

---

### Tâche 3 : exécuteur robuste et visite locale

**Files :**
- Modify : `cowork/actions.py`, `tests/test_actions.py`
- Create : `cowork/visite.py`, `tests/test_visite.py`
- Modify : `cowork/surete.py`, `tests/test_surete.py` (noms anglais), `config.py`

**Interfaces :**
- Consumes : `Action`, `valider` (Tâche 1).
- Produces :
  - `@dataclass(frozen=True) class Resultat: ok: bool; corps: str; diff: str | None = None; effet: tuple[str, str] | None = None; code: int | None = None` (`effet` = `("cree"|"modifie"|"supprime", chemin)`).
  - `Executeur(dossier: Path, delai: float, taille_max: int, lancer=lancer_powershell, processus: "GestionnaireProcessus | None" = None, ports_interdits: frozenset[int] = frozenset(), delai_visite: float = 10.0)`, `.executer(action) -> Resultat`.
  - `lancer_powershell(texte, dossier, delai) -> tuple[int, str]` : `Popen` + `communicate(timeout)` ; au dépassement, `tuer_arbre(pid)` puis relève `subprocess.TimeoutExpired`.
  - `tuer_arbre(pid: int) -> None` : `taskkill /T /F /PID` (sortie ignorée).
  - `visiter(url: str, methode: str, corps: str | None, ports_interdits: frozenset[int], delai: float, taille_max: int) -> Resultat` (urllib, sans proxy).
  - `classer(action) -> Verdict` : `delete` → dangereuse ; `run`/`start` → `analyser_commande(command)` ; le reste sûr.

- [ ] **Étape 1 : tests** (`tests/test_actions.py`, en plus des cas existants adaptés aux noms anglais)
- `test_fichier_absent_renvoie_une_erreur` : `read` de `x.txt` absent → `ok False`, corps contient `"not found"`.
- `test_champ_manquant_renvoie_une_erreur` : `Action("create", {"path": "a"})` → `'missing field "content"'`.
- `test_action_inconnue` → `ok False`, corps commence par `'unknown action'`.
- `test_lister_un_fichier` (`list` sur un fichier) → `ok False`.
- `test_chemins_windows` : `create` `app\\views\\x.html` puis `read` `app/views/x.html` → même contenu ; `read` `C:\\Windows\\win.ini` et `..\\x` → `ok False`, `"outside the working folder"`.
- `test_creer_nouveau` → `effet == ("cree", "a.txt")`, corps `"a.txt created (2 lines)"`.
- `test_reecrire_donne_un_diff` : fichier existant → `effet[0] == "modifie"`, `diff` contient `"-ancien"` et `"+nouveau"`.
- `test_edit_unique` → diff unifié (lignes `-`/`+`), `effet == ("modifie", ...)`.
- `test_edit_introuvable_montre_le_passage_proche` : fichier `def f():\n    return 1\n`, `old` `"def f():\n  return 1"` → `ok False`, corps contient `"Closest passage (lines 1-2)"` et `"    return 1"`.
- `test_edit_plusieurs_fois` : `old` présent 2 fois → `"appears 2 times"`.
- `test_supprimer_effet` → `("supprime", "a.txt")`.
- `test_commande_code_de_sortie` : faux `lancer` → `(1, "boum")` → `ok False`, `code == 1`.
- `test_commande_trop_longue_conseille_start` : faux `lancer` qui lève `TimeoutExpired` → corps contient `"use start"`.
- `test_aucune_exception_ne_sort` : `read` d'un dossier (IsADirectoryError/PermissionError) → `Resultat(ok=False)`.

`tests/test_visite.py` (serveur `http.server` local dans un fil, port libre) :
- `test_visite_get` → `ok`, corps commence par `"HTTP 200"`.
- `test_visite_post_avec_corps` (handler qui renvoie le corps reçu).
- `test_visite_hors_localhost` : `http://example.com/` → `ok False`, `"only localhost"`.
- `test_visite_port_interdit` : port dans `ports_interdits` → `ok False`, `"not allowed"`.
- `test_visite_refusee` (port fermé) → `ok False`, `"connection"`.
- `test_visite_erreur_http` (404) → `ok False`, corps `"HTTP 404"` + début du corps.

`tests/test_surete.py` : remplacer les noms français par `delete`/`run` ; ajouter `test_start_analyse_comme_run` (`start` `Remove-Item -Recurse x` → dangereuse).

- [ ] **Étape 2 : échec constaté.**
- [ ] **Étape 3 : implémenter.** Aiguillage `nom → méthode` ; `valider` d'abord ; `try/except Exception` autour de chaque action → `Resultat(False, f"{raison}")` (`FileNotFoundError` → `"file not found: <path>"`, `NotADirectoryError`, `IsADirectoryError`, `PermissionError` → message court anglais). Chemin : `chemin.replace("\\", "/")` avant résolution. Passage proche : fenêtre glissante de `len(old.splitlines())` lignes sur au plus 5000 lignes du fichier, `difflib.SequenceMatcher(None, old, fenetre).ratio()`, meilleure fenêtre si ratio ≥ 0.5 sinon `"No similar passage found."`. Diff : `difflib.unified_diff(..., n=2, lineterm="")` sans les en-têtes `---/+++`, 200 lignes max. `visit` : schéma `http`, hôte ∈ `localhost`, `127.0.0.1`, `::1` ; `urllib.request.build_opener(urllib.request.ProxyHandler({}))` ; corps texte coupé à `taille_max` ; réponse `HTTP <code> <type> <octets> bytes\n<corps>`. `start/logs/stop` délèguent à `processus` (Tâche 4) ; sans gestionnaire → `ok False`. `config.py` : ajouter les constantes des Global Constraints.
- [ ] **Étape 4 : vert** (`pytest tests/test_actions.py tests/test_visite.py tests/test_surete.py -q`).
- [ ] **Étape 5 : commit** — `feat(cowork): actions sans plantage, passage proche, diff, visite locale`

---

### Tâche 4 : processus en arrière-plan

**Files :**
- Create : `cowork/processus.py`, `tests/test_processus.py`
- Modify : `cowork/actions.py` (branchement `start/logs/stop`)

**Interfaces :**
- Consumes : `Resultat`, `tuer_arbre` (Tâche 3).
- Produces :
  - `GestionnaireProcessus(dossier: Path, max_processus: int, attente_demarrage: float, taille_max: int, commande=lambda texte: ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SORTIE_UTF8 + texte], au_changement: Callable[[list[dict]], None] = lambda liste: None)`
  - `.demarrer(commande: str) -> Resultat` · `.sortie(numero: str) -> Resultat` · `.arreter(numero: str) -> Resultat` · `.arreter_tout() -> None` · `.liste() -> list[dict]` (`{"id": 1, "commande": str, "depuis": iso, "actif": bool, "code": int | None}`).
  - Numéros `#1, #2…` par gestionnaire ; `numero` accepte `"1"` et `"#1"`.

- [ ] **Étape 1 : tests** (vrais processus `sys.executable -c`, `commande=lambda t: [sys.executable, "-c", t]`, `attente_demarrage=0.5`)
- `test_demarrer_puis_sortie` : script qui écrit `pret` puis dort 30 s → `ok`, corps commence par `"started #1 (pid "` et contient `"pret"` ; `liste()[0]["actif"] is True`.
- `test_processus_muet_ne_bloque_pas` : script qui dort 30 s → corps contient `"(no output yet)"`, durée < 3 s.
- `test_mort_au_demarrage` : script `raise SystemExit(3)` après un `print("boum")` → `ok False`, `code == 3`, corps contient `"boum"`.
- `test_logs_seulement_le_nouveau` : 2 appels à `sortie("1")` ne renvoient pas deux fois la même ligne ; 2ᵉ appel sans nouveauté → `"(no new output)"`.
- `test_arreter` → `ok`, `liste()[0]["actif"] is False` ; `arreter("9")` → `ok False`, `"no process #9"`.
- `test_limite` : `max_processus=1`, 2ᵉ `demarrer` pendant que le 1ᵉʳ tourne → `ok False`, `"stop one first"`.
- `test_arreter_tout` et `test_au_changement_appele` (appelé au démarrage et à l'arrêt).

- [ ] **Étape 2 : échec constaté.**
- [ ] **Étape 3 : implémenter.** `Popen(stdout=PIPE, stderr=STDOUT, cwd=dossier, env PYTHONUTF8=1, encoding utf-8 errors replace, creationflags=CREATE_NEW_PROCESS_GROUP sous Windows)` ; un fil lecteur par processus ajoute les lignes à un tampon borné (`collections.deque`, ~`taille_max` caractères) et un curseur de lecture ; arrêt = `tuer_arbre(pid)` puis `wait(5)`. Un processus terminé reste listé (`actif False`, `code`). `au_changement(liste())` à chaque démarrage/arrêt/mort détectée. Dans `Executeur`, `start` → `processus.demarrer(command)`, `logs` → `.sortie(id)`, `stop` → `.arreter(id)`.
- [ ] **Étape 4 : vert.**
- [ ] **Étape 5 : commit** — `feat(cowork): processus en arrière-plan (start, logs, stop)`

---

### Tâche 5 : tâche, lots, plan et fin contrôlée

**Files :**
- Create : `cowork/tache.py`, `tests/test_tache.py`
- Modify : `cowork/boucle.py` (réécrit), `tests/test_boucle.py` (réécrit)

**Interfaces :**
- Consumes : `lire_actions`, `formater_resultats`, `LigneResultat`, `rappel_pour`, `est_erreur_gemini`, `resume_action`, `Resultat`, `Verdict`.
- Produces (`cowork/tache.py`) :
  - `lire_plan(steps) -> list[dict]` : `steps` liste ou texte multi-lignes ; `[x]`/`[X]` → `fait True`, `[ ]` ou rien → `False` ; `{"texte": str, "fait": bool}`.
  - `@dataclass class EtatTache` : `plan: list[dict]`, `effets: list[tuple[str, str]]`, `commandes: list[dict]` (`{"texte", "code"}`), `ecrit_depuis_verif: bool`, `verif_demandee: bool`, `relances: int`, `verifications: int` ; méthodes `noter(action: Action, resultat: Resultat)`, `etapes_restantes() -> list[str]`, `bilan(processus: list[dict]) -> dict`, `vers_dict() -> dict`, `@classmethod depuis_dict(d) -> EtatTache`.
  - `bilan` : `{"crees": [...], "modifies": [...], "supprimes": [...], "commandes": [...], "verifications": int, "plan_inacheve": [...], "processus": [...]}` ; un fichier créé puis modifié reste dans `crees` seulement ; dédoublonné, ordre d'apparition.
  - Vérification : `run`, `start`, `visit` (réussis ou non) remettent `ecrit_depuis_verif = False` et comptent dans `verifications` ; `create/edit/delete` réussis le mettent à `True` sauf si toutes les écritures depuis la dernière vérif sont en `.md`/`.txt`.
- Produces (`cowork/boucle.py`) :
  - `@dataclass(frozen=True) class Reglages: max_tours: int; max_actions: int; echecs_max: int; taille_max: int; taille_max_message: int; relances_fin_max: int`
  - `@dataclass(frozen=True) class Branchements: envoyer: Callable[[str], str]; executer: Callable[[Action], Resultat]; classer: Callable[[Action], Verdict]; demander_accord: Callable[[Action, str], bool]; emettre: Callable[[dict], None]`
  - `executer_tache(message: str, tache: EtatTache, b: Branchements, r: Reglages) -> None`
  - Évènements émis (français, internes) : `plan {etapes}`, `action {action, champs}`, `resultat {ok, corps, diff, code}`, `saute {action, champs}`, `demande`, `refus`, `erreur_format {corps}`, `erreur_gemini {corps}`, `relance_fin {raison}`, `termine {resume}`, `question {question, tache}`, `limite`, `erreur {corps}`.

- [ ] **Étape 1 : tests** — `tests/test_tache.py` : `lire_plan` (liste, texte, `[X]`), bilan (créé puis modifié → `crees` seul), vérif (`.md` seul ne déclenche pas), `vers_dict`/`depuis_dict` aller-retour.
`tests/test_boucle.py` (faux envoyeur scripté, faux exécuteur qui note les actions, comme aujourd'hui) :
- `test_lot_execute_dans_l_ordre` : un message à 3 `create` → exécuteur appelé 3 fois, un seul message de résultats renvoyé contenant `[1]`, `[2]`, `[3]`.
- `test_lot_s_arrete_a_la_premiere_erreur` : 2ᵉ action en échec → 3ᵉ non exécutée, `"[3] … SKIPPED"`, évènement `saute`.
- `test_accord_refuse_au_milieu_du_lot` → action refusée `ERROR`, suivantes `SKIPPED`.
- `test_trop_d_actions` : 12 actions, `max_actions=10` → 10 exécutées, résultats contiennent `"only the first 10"`.
- `test_plan_emis` : `plan` → évènement `plan` avec `etapes`, résultat `OK` `"plan saved (0/2 done)"`.
- `test_done_refuse_si_plan_inacheve` : plan `[ ] a`, puis `done` → message suivant commence par `"NOT FINISHED"` et cite `a`, évènement `relance_fin` ; puis plan `[x] a` + `done` → `termine`.
- `test_done_demande_une_verification_une_fois` : `create a.py` puis `done` → `"Verify your work first"` ; `done` à nouveau → `termine`.
- `test_pas_de_verification_pour_du_texte` : `create notes.md` puis `done` → `termine` direct.
- `test_relances_bornees` : plan jamais coché, `done` ×3 avec `relances_fin_max=2` → `termine` au 3ᵉ.
- `test_done_saute_si_une_action_echoue` : `[create (échoue), done]` → pas de `termine`, `done` en `SKIPPED`.
- `test_ask_met_en_pause` : `ask` → évènement `question` avec `question` et `tache` (dict), plus aucun envoi.
- `test_format_casse_garde_le_texte` : réponse prose → `erreur_format` avec `corps` = la prose ; 3 de suite → `termine` `"Format non compris, arrêt."`.
- `test_limite_de_tours` → `limite`.
- `test_erreur_gemini_renvoie_puis_arrete` (gardé).

- [ ] **Étape 2 : échec constaté.**
- [ ] **Étape 3 : implémenter.** Boucle : pour chaque tour, `envoyer` → (erreur Gemini : logique actuelle) → `lire_actions` ; vide → format cassé ; sinon traiter le lot (≤ `max_actions`) action par action : `valider` → `ERROR` ; `plan` → `tache.plan = lire_plan(...)`, OK ; `ask`/`done` hors dernière position ou après un échec → `SKIPPED` ; action normale → `classer`, accord, `executer`, `tache.noter`. Un `done` en dernier, lot réussi : contrôle (plan restant → `NOT FINISHED: unchecked plan steps: …` ; sinon `ecrit_depuis_verif and not verif_demandee` → texte de vérif de la spec, `verif_demandee = True`) tant que `relances < relances_fin_max` (chaque refus `relances += 1`) ; accepté → `termine {resume: summary}` et retour. `ask` en dernier → `question {question, tache: tache.vers_dict()}` et retour. Message suivant = `formater_resultats(...)` (+ texte de refus de fin s'il y en a, avant le pied).
- [ ] **Étape 4 : vert.**
- [ ] **Étape 5 : commit** — `feat(cowork): lots d'actions, plan, fin contrôlée et bilan`

---

### Tâche 6 : service Cowork, historique et routes locales

**Files :**
- Create : `agent_first/diffuseur.py`, `agent_first/cache_modes.py`
- Modify : `agent_first/cowork_service.py` (réécrit), `agent_first/historique.py`, `agent_first/serveur.py`, `agent_first/__main__.py`
- Test : `tests/test_cowork_api.py` (réécrit), `tests/test_historique.py`, `tests/test_serveur.py`

**Interfaces :**
- Consumes : tâches 1–5 (`cadre`, `arborescence`, `executer_tache`, `Reglages`, `Branchements`, `EtatTache`, `GestionnaireProcessus`, `classer`).
- Produces :
  - `Diffuseur` : `abonner() -> queue.Queue`, `desabonner(q)`, `publier(ev: dict)` (non bloquant, file pleine → ignorée).
  - `CacheModes(file, chrome_lance, par_defaut)` : `lire() -> Modes`, `oublier()` (logique extraite de `serveur.modeles`).
  - `Historique.creer(..., source: str = "app")` ; `Conversation.source: str = "app"` (colonne migrée, placée avant `nb_messages`) ; `Historique.derniere_etape(identifiant: str, types: set[str]) -> dict | None`.
  - `ServiceCowork(file, historique, fabrique_executeur: Callable[[Path, GestionnaireProcessus], Executeur], reglages: Reglages, fabrique_processus: Callable[[Path, Callable], GestionnaireProcessus], delai_accord=600.0, delai_reponse=None, diffuseur: Diffuseur | None = None, max_entrees=150)`
    - `demarrer(conversation_id, dossier, adresse, texte, modele, niveau) -> None` (statut `queued` jusqu'au début réel)
    - `en_cours(conversation_id) -> bool` · `flux(conversation_id, depuis: int = 0) -> Iterator[str]` (rejoue puis suit ; plusieurs lecteurs) · `instantane(conversation_id, lire: Callable[[], T]) -> tuple[T, dict]` (`{"en_cours": bool, "depuis": int}`, sous le verrou d'émission) · `etat(conversation_id) -> dict` (`statut`, `plan`, `evenements`, `resume`, `bilan` ; reconstruit depuis l'historique si pas de session) · `decider(...)`, `arreter(...)` (inchangés) · `processus(conversation_id) -> list[dict]` · `arreter_processus(conversation_id, numero) -> Resultat` · `arreter_tout() -> None`.
    - Statuts : `queued`, `running`, `waiting_approval`, `question`, `done`, `error`, `stopped` (`limite` et `arret` → `stopped`).
    - Tout évènement de fin (`termine`, `limite`, `arret`, `erreur`) reçoit `bilan = tache.bilan(processus)` ; `question` aussi. Évènements `statut {statut}` émis à chaque changement ; `processus {liste}` à chaque changement.
    - Reprise après `question` : si `derniere_etape(id, {"question","termine","limite","arret","erreur"})` est une `question`, `EtatTache.depuis_dict(ev["tache"])` et `reponse=True` dans `cadre`.
    - `LAST TASK` : depuis la dernière fin (`termine`/`limite`/`arret`/`erreur`) : statut, `resume`, fichiers du bilan, `plan_inacheve`.
  - Routes locales ajoutées (`serveur.py`) : `GET /api/cowork/{id}/flux?depuis=N` ; `GET /api/conversations/{id}` renvoie en plus `"tache": {"en_cours", "depuis"}` (via `instantane`) ; `GET /api/cowork/{id}/processus` ; `POST /api/cowork/{id}/processus/{n}/arreter` ; `GET /api/evenements` (SSE du diffuseur, `: ping` toutes les 15 s) ; `POST /api/cowork/{id}/messages` → 409 si `en_cours`.
  - Le diffuseur publie `{conversation_id, type, etape, statut?}` pour chaque évènement émis.

- [ ] **Étape 1 : tests** (`tests/test_cowork_api.py`, faux pilote qui enregistre les textes reçus)
- `test_chaque_demande_part_avec_le_cadre` : deux messages successifs → les deux textes reçus par le pilote commencent par `"[AGENT FIRST · COWORK]"` et contiennent la demande.
- `test_tache_cree_un_fichier` (adapté, actions anglaises), `test_etapes_enregistrees`, `test_decision_debloque_une_action_dangereuse`, `test_flux_apres_la_fin_ne_bloque_pas` (gardés, adaptés).
- `test_deux_lecteurs_du_flux` : deux `flux()` en parallèle reçoivent les mêmes évènements.
- `test_flux_depuis` : `flux(id, depuis=2)` ne renvoie pas les étapes 0 et 1.
- `test_question_puis_reponse_reprend_la_tache` : `[plan [ ] a, ask]` puis 2ᵉ message → texte reçu contient `"USER ANSWER TO YOUR QUESTION:"`, un `done` immédiat est refusé (`NOT FINISHED`).
- `test_reprise_apres_redemarrage` : même scénario avec un **nouveau** `ServiceCowork` sur le même historique entre les deux messages.
- `test_bilan_dans_termine` : `termine["bilan"]["crees"] == ["a.txt"]`.
- `test_derniere_tache_dans_le_cadre` : 2ᵉ demande contient `"LAST TASK:"` et `"a.txt"`.
- `test_409_si_tache_en_cours`.
- `test_processus_survit_a_la_tache_et_s_arrete` : `start` (vrai `sys.executable -c` qui dort) puis `done` → `GET /api/cowork/{id}/processus` liste `#1 actif` ; `POST …/processus/1/arreter` → inactif.
- `test_conversation_renvoie_tache_en_cours`.
- `test_diffuseur_recoit_la_demande_d_accord`.
`tests/test_historique.py` : `test_source_par_defaut_app`, `test_source_api`, `test_migration_ajoute_source`, `test_derniere_etape`.

- [ ] **Étape 2 : échec constaté.**
- [ ] **Étape 3 : implémenter.** Session : `evenements: list[dict]`, `condition: threading.Condition`, `fini: bool`, `statut` ; `_emettre` (sous `condition`) : complète l'évènement (`etape`, `bilan` si fin), l'enregistre (`ajouter_etape`), l'ajoute à la liste, `notify_all`, publie au diffuseur. Sessions finies gardées (20 dernières). Processus : un `GestionnaireProcessus` par conversation créé à la 1ʳᵉ tâche, `au_changement` → émet `processus` si une session tourne et publie au diffuseur sinon. `__main__.py` : nouvelles signatures (`Reglages` depuis `config`), `ports_interdits = {PORT_AGENT, PORT_API, PORT_CHROME}`, `cowork.arreter_tout()` dans le `finally`. `serveur.py` utilise `CacheModes`.
- [ ] **Étape 4 : vert** — `pytest -q` complet.
- [ ] **Étape 5 : commit** — `feat(cowork): cadre à chaque demande, reprise après question, flux rejouable, processus par conversation`

---

### Tâche 7 : API réseau (OpenAI + Cowork)

**Files :**
- Create : `agent_first/cle_api.py`, `agent_first/openai_compat.py`, `agent_first/api_reseau.py`, `tests/test_cle_api.py`, `tests/test_openai_compat.py`, `tests/test_api_reseau.py`
- Modify : `agent_first/__main__.py`, `agent_first/serveur.py` (routes `GET /api/api-reseau`, `POST /api/api-reseau/cle`), `config.py`

**Interfaces :**
- Consumes : `ServiceCowork` (Tâche 6 : `demarrer`, `en_cours`, `etat`, `flux`, `decider`, `arreter`, `arreter_processus`), `CacheModes`, `Historique`, `FileAttente`.
- Produces :
  - `cle_api.py` : `lire_ou_creer_cle(fichier: Path) -> str` ; `class GardeCle(fichier: Path, essais_max=10, fenetre=60.0, blocage=60.0, horloge=time.monotonic)` avec `.cle`, `.regenerer() -> str`, `.verifier(ip: str, entete: str | None) -> int | None` (`None` = OK, `401`, `429`), comparaison `hmac.compare_digest`.
  - `openai_compat.py` : `niveau_depuis_effort(effort: str | None) -> str | None` (`low→Min.`, `medium→Moyen`, `high→Max.`) ; `texte_message(contenu: str | list) -> str` ; `empreinte(modele: str | None, messages: list[dict]) -> str` (sha256 du JSON trié) ; `mettre_a_plat(messages: list[dict]) -> str` ; `completion(contenu: str, modele: str, invite: str) -> dict` ; `morceaux(contenu: str, modele: str) -> Iterator[str]` ; `vers_api(evenement: dict) -> dict` (traduction des types et clés, section 8.3 ; table `TYPES` et `CLES` dans le module) ; `adresse_reseau() -> str` (IP locale via socket UDP non connectée à Internet, repli `127.0.0.1`).
  - `api_reseau.py` : `creer_api_reseau(file, historique, cowork, garde: GardeCle, modes: CacheModes, delai: float) -> FastAPI`.
  - Routes : spec 8.2 et 8.3. Erreurs au format OpenAI `{"error": {"message", "type", "code"}}`. Mémoire des conversations API : `dict[empreinte -> (conversation_id, adresse)]`, 500 entrées max (plus anciennes retirées).
  - `__main__.py` : si `API_ACTIVE`, `uvicorn.Server(uvicorn.Config(api, host=HOTE_API, port=PORT_API, log_level="warning"))` lancé dans un fil daemon `server.run()` ; affiche `API réseau : http://<ip>:8766/v1 — clé : <clé>` ; `should_exit = True` dans le `finally`.

- [ ] **Étape 1 : tests**
`tests/test_cle_api.py` : clé créée une fois puis relue identique ; `verifier` → `None` avec `"Bearer <clé>"`, `401` sans en-tête ou mauvaise clé ; 10 mauvaises → la 11ᵉ (même bonne) `429` ; après `blocage` (horloge factice) → OK ; `regenerer` change la clé et l'ancienne → 401.
`tests/test_openai_compat.py` : `niveau_depuis_effort("high") == "Max."`, `None` → `None` ; `texte_message([{"type":"text","text":"a"},{"type":"text","text":"b"}]) == "a\nb"` ; `mettre_a_plat` d'un seul message utilisateur = son texte ; avec `system` + historique → contient `"[System instructions]"`, `"User:"`, `"Assistant:"`, `"[New message]"` ; `empreinte` stable et sensible au modèle ; `completion(...)["choices"][0]["message"]["content"]` ; `morceaux` finit par `"data: [DONE]\n\n"` ; `vers_api({"type":"resultat","corps":"x","etape":3})` → `{"type":"result","output":"x","step":3}` ; bilan traduit (`crees→created`).
`tests/test_api_reseau.py` (faux pilote, `TestClient`) :
- `test_sans_cle_401` sur `/v1/models` ; `test_docs_sans_cle` (`/docs` → 200).
- `test_models` → `data[*].id` = noms de `Modes`.
- `test_chat_completion` → contenu = réponse du faux pilote ; une conversation `source == "api"` existe dans l'historique.
- `test_suite_de_conversation` : 2ᵉ appel avec l'historique complet + nouveau message → le faux pilote reçoit **seulement** le nouveau message et la même `adresse`.
- `test_historique_inconnu_mis_a_plat` → le pilote reçoit `"[Conversation so far]"`, adresse `None`.
- `test_stream` → `text/event-stream`, finit par `[DONE]`.
- `test_reasoning_effort` → pilote reçoit `niveau == "Max."`.
- `test_erreur_pilote_502` (pilote qui lève `ErreurPilote`).
- `test_cowork_cree_et_suit` : `POST /v1/cowork` (`folder=tmp_path`) → `{"id","status"}` ; `GET /v1/cowork/{id}/events` contient un évènement `"done"` avec `report.created`.
- `test_cowork_dossier_refuse` : `C:\\` et `C:\\Windows` et un dossier absent → 400.
- `test_cowork_decision` : action `delete` → `approval_required` puis `POST decision {"step", "approve": true}` → fichier supprimé.
- `test_cowork_409` ; `test_cowork_etat` (`GET /v1/cowork/{id}` → `status` ∈ statuts, après la fin `done`).
`tests/test_serveur.py` : `test_api_reseau_infos` (`GET /api/api-reseau` → `active`, `adresse`, `cle`) ; `test_regenerer_cle`.

- [ ] **Étape 2 : échec constaté.**
- [ ] **Étape 3 : implémenter.** Auth : dépendance FastAPI sur le routeur `/v1` (`request.client.host`, en-tête `Authorization`) ; `/docs` et `/openapi.json` hors dépendance. Chat : `historique.creer(modele, niveau, "chat", None, source="api")`, messages `toi`/`gemini` enregistrés, `file.soumettre(...).result(timeout=delai)` (504 sinon). Dossier Cowork refusé si : pas absolu, absent, racine de lecteur (`Path(folder).parent == Path(folder)`), ou sous `%SystemRoot%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`. `events` = `flux` traduit par `vers_api`.
- [ ] **Étape 4 : vert** — `pytest -q`.
- [ ] **Étape 5 : commit** — `feat(api): API réseau avec clé, format OpenAI et routes Cowork`

---

### Tâche 8 : rendu visuel de l'app

**Files :**
- Modify : `agent_first/web/outils_cowork.js`, `agent_first/web/app.js`, `agent_first/web/app.css`, `agent_first/web/index.html`, `tests/web/outils_cowork.test.mjs`
- Create : `tests/test_libelles.py` (le catalogue Python et les libellés JS concordent)

**Interfaces :**
- Consumes : évènements de la Tâche 5/6, routes locales de la Tâche 6/7.
- Produces (`outils_cowork.js`) : `libelleEtape(ev)` (noms anglais **et** anciens noms français via `ANCIENS = {creer: "create", …}`) ; `avancementPlan(etapes) -> {faites, total}` ; `lignesBilan(bilan) -> {compteurs: string, fichiers: string[]}` ; `infoResultat(action, corps) -> string` (`visit` → code HTTP, `start` → `#n`, `read` → nombre de lignes) ; `resumeDiff` et `nombreLignes` gardés (le diff unifié peut contenir des lignes de contexte : on compte seulement `+`/`-` hors `+++`/`---`).
- Verbes : `list→List read→Read search→Search create→Write edit→Edit delete→Delete run→Run start→Start logs→Logs stop→Stop visit→Visit`.

- [ ] **Étape 1 : tests**
`tests/web/outils_cowork.test.mjs` : `libelleEtape({type:"action", action:"create", champs:{path:"a"}})` → `verbe "Write"`, `detail "a"` ; `libelleEtape({type:"action", action:"creer", champs:{chemin:"a"}})` → même résultat (ancien nom) ; `avancementPlan([{fait:true},{fait:false}])` → `{faites:1,total:2}` ; `lignesBilan({crees:["a"],modifies:["b"],supprimes:[],commandes:[{texte:"x",code:1}],verifications:2,plan_inacheve:[],processus:[]})` → compteurs contient `"1 créé"`, `"1 modifié"`, `"1 en échec"` ; `infoResultat("visit", "HTTP 500 text/html 10 bytes\n…") === "500"` ; `resumeDiff` ignore `---`/`+++` ; types `saute`, `relance_fin`, `question` ont un titre.
`tests/test_libelles.py` : chaque nom de `CATALOGUE` hors `plan/ask/done` apparaît comme clé dans `ACTIONS` de `outils_cowork.js` (regex sur le fichier).

- [ ] **Étape 2 : échec constaté** — `node --test tests/web/` et `pytest tests/test_libelles.py`.
- [ ] **Étape 3 : implémenter.**
  - `outils_cowork.js` : fonctions ci-dessus.
  - `app.js` : `creerRenduCowork` gère `plan` (une carte par segment : mise à jour si aucune bulle `toi` depuis la dernière carte, sinon nouvelle), `saute` (ligne grise), `erreur_format` (`details` repliable : « Gemini n'a pas respecté le format, rappel envoyé » + son texte), `relance_fin` (note ambre « Fin refusée : … »), `termine` (bulle + carte Bilan), `question` (carte question + focus de la saisie), `processus` (en-tête). Champs lus en anglais avec repli français (`champs.path ?? champs.chemin`). `ouvrirConversation` : si `tache.en_cours`, `ecouterFlux(id, tache.depuis)` ; charge `GET /api/cowork/{id}/processus` pour l'en-tête. Flux global `EventSource("/api/evenements")` au démarrage : `demande` d'une conversation non suivie → marque `attente` dans la barre et bandeau « Une tâche attend ton accord » (bouton Ouvrir) ; `statut` → rafraîchit la barre (point « en cours » aussi pour les tâches API) ; fin/accord → retire la marque. Paramètres : section « API réseau » (adresse, clé masquée `••••` + 4 derniers caractères, Copier, Régénérer avec confirmation).
  - `index.html` : `#processus` dans l'en-tête de la discussion, `#bandeau-accord`, section API dans le dialogue Paramètres.
  - `app.css` : `.carte-plan`, `.plan-case`, `.carte-bilan`, `.carte-question`, `.pilule-processus`, `.bandeau`, `.etape.sautee`, `.format-casse`, `.marque.attente` — mêmes jetons (`--bordure`, `--texte-2`, `--accent`, `--vert`, `--ambre`, `--rouge`, police mono), rien de nouveau en couleur.
- [ ] **Étape 4 : vert** + vérification visuelle : lancer Agent First (`.venv\Scripts\python -m agent_first`), ouvrir `http://127.0.0.1:8765/`, ouvrir l'ancienne conversation Cowork (étapes françaises lisibles), le dialogue Paramètres (section API). Capture d'écran.
- [ ] **Étape 5 : commit** — `feat(web): plan, bilan, question, processus et alertes d'accord dans le fil Cowork`

---

### Tâche 9 : README, vérification finale, relecture, push

**Files :** Modify : `README.md`

- [ ] **Étape 1 :** README : section « API réseau » (adresse, clé dans Paramètres, exemples `curl` et client OpenAI Python avec `base_url`, routes Cowork), mise à jour de la section Cowork (actions anglaises, processus).
- [ ] **Étape 2 :** `.venv\Scripts\python -m pytest -q` et `node --test tests/web/` → tout vert.
- [ ] **Étape 3 :** relecture de toute la branche par un relecteur indépendant ; corriger ce qui est confirmé.
- [ ] **Étape 4 :** commit `docs: README v3 (API réseau, Cowork)` ; fusion sur `main` (avance rapide) ; `git push origin main`.
