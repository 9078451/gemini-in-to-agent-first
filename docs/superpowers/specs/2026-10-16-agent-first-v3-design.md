# agent.first v3 — Cowork tenu, plus puissant, API réseau — fiche de conception

Date : 2026-10-16
Statut : à valider
S'ajoute à la fiche Cowork (`2026-10-16-cowork-design.md`) ; le pilote, la file
d'attente, l'historique, l'app web et le garde-fou de sûreté sont gardés.

## 1. Pourquoi

Une vraie tâche Cowork (16/10, dossier « TEST IA », 213 étapes) a montré que
Gemini sort de son rôle :

| Constat | Cause dans le code |
|---|---|
| Après ton 2ᵉ message, Gemini répond comme un chat (3 « format non compris », arrêt, deux fois) | le mode d'emploi n'est envoyé qu'au 1er message ; les suivants partent bruts (`cowork_service.demarrer`) |
| « TERMINÉ » après 2 fichiers en annonçant « toutes les vues refondues » ; tu as dû relancer 5 fois | rien ne contrôle la fin ; le résumé de Gemini est cru sur parole |
| Le serveur plantait au lancement, c'est toi qui as trouvé l'erreur | aucune étape de vérification demandée |
| « Lance le serveur » → « exécutez simplement python server.py » | une commande bloque jusqu'à 120 s : impossible de lancer un serveur |
| Lire un fichier absent, ou une action sans un champ, fait planter toute la tâche | `Executeur` n'attrape que `HorsDossier` |
| Ce que Gemini a écrit hors format est perdu | l'étape `erreur_format` ne garde pas le texte |
| Chaque petite action coûte un aller-retour (~10 s) | une seule action lue par message, les suivantes ignorées en silence |

## 2. But et critères de réussite

Gemini reste un agent qui **agit** (jamais un chat qui conseille), voit et
vérifie son travail, et ne peut pas déclarer fini ce qui ne l'est pas. Le
protocole parle anglais. Agent First devient aussi utilisable par d'autres
programmes, depuis le réseau, avec une clé.

**C'est réussi quand :**

1. Coller une erreur dans une conversation Cowork déjà commencée fait corriger
   le code par Gemini (actions), sans « format non compris ».
2. « Fais un serveur web et lance-le » : Gemini fait un plan, crée les fichiers,
   lance le serveur en arrière-plan, l'ouvre (`visit`) pour vérifier, corrige
   s'il plante, puis finit ; le serveur reste lancé et l'app l'indique.
3. Un « done » avec des étapes du plan non cochées est refusé et Gemini continue.
4. La fin affiche un **bilan factuel** (fichiers créés/modifiés/supprimés,
   commandes et leur code de sortie) calculé par Agent First.
5. Lire un fichier absent renvoie une ERREUR à Gemini ; la tâche continue.
6. Depuis un autre PC du réseau, un client OpenAI (`base_url=http://<pc>:8766/v1`,
   avec la clé) discute avec Gemini ; sans la clé : refus 401.
7. Depuis un autre PC, `POST /v1/cowork` lance une tâche Cowork et ses étapes
   arrivent en direct (SSE).

## 3. Ce que tu as dit / ce que j'ai décidé

| Point | Source |
|---|---|
| Gemini doit rester dans son rôle, proprement | toi |
| Plus puissant, code plus propre | toi |
| Ordres (actions) en anglais : `create` au lieu de `creer`… | toi |
| Gemini doit mieux comprendre la demande | toi |
| Améliorer le rendu visuel | toi |
| Serveur d'API appelable par d'autres services, joignable depuis le réseau, clé obligatoire, format OpenAI + routes Cowork | toi |
| Le mode d'emploi envoyé à Gemini est en anglais ; Gemini te parle en français (plan, questions, résumé) | décision (Claude) |
| Le mode d'emploi complet repart avec **chaque** demande de l'utilisateur (pas seulement la 1ʳᵉ) | décision (Claude) |
| Les anciens noms français (`creer`, `chemin`…) restent acceptés en lecture | décision (Claude) |
| Le code garde ses noms français ; seul le protocole avec Gemini et l'API externe sont en anglais | décision (Claude) |
| Le plan est fortement demandé mais pas imposé ; seule la fin est contrôlée | décision (Claude) |
| L'API réseau écoute sur un **second port** (8766) ; l'app reste sur 127.0.0.1:8765 sans clé | décision (Claude) |
| L'API réseau est active par défaut (tu l'as demandée) ; désactivable dans `config.py` | décision (Claude) |
| Une **tâche** va de ta demande à `done`/arrêt ; la réponse à un `ask` continue la même tâche (5.1) | décision (Claude) |
| Les actions sur fichiers restent **refusées** hors du dossier de travail (comme aujourd'hui) ; le texte envoyé à Gemini le dit | décision (Claude) |
| `visit` ne peut pas joindre les ports d'Agent First (8765, 8766) ni celui de Chrome (9222) | décision (Claude) |
| Une tâche lancée par l'API pendant qu'une autre tourne est **mise en file** (état `queued`) | décision (Claude) |
| Une demande d'accord d'une tâche que l'app n'affiche pas est signalée partout dans l'app (7) | décision (Claude) |

## 4. Le protocole avec Gemini (anglais)

### 4.1 Les actions

Chaque message de Gemini ne contient **que** des actions JSON : un bloc
```` ```json ```` avec un objet action, ou une liste d'objets (plusieurs blocs
sont aussi acceptés).

| action | champs (requis, *optionnels*) | effet | ancien nom |
|---|---|---|---|
| `list` | *`path`* (défaut `.`) | liste un dossier | `lister` |
| `read` | `path` | lit un fichier (coupé si long) | `lire` |
| `search` | `pattern`, *`glob`* | cherche un texte | `chercher` |
| `create` | `path`, `content` | crée ou réécrit un fichier | `creer` |
| `edit` | `path`, `old`, `new` | remplace un passage exact et unique | `modifier` |
| `delete` | `path` | supprime (accord requis) | `supprimer` |
| `run` | `command` | commande PowerShell qui se termine | `commande` |
| `start` | `command` | lance un processus long (serveur) en arrière-plan | — |
| `logs` | `id` | nouvelle sortie d'un processus lancé | — |
| `stop` | `id` | arrête un processus lancé (et ses enfants) | — |
| `visit` | `url`, *`method`*, *`body`* | requête HTTP vers **localhost uniquement** | — |
| `plan` | `steps` | pose ou met à jour le plan (`"[ ] …"` / `"[x] …"`) | — |
| `ask` | `question` | pose une question à l'utilisateur ; la tâche s'arrête en attendant sa réponse | — |
| `done` | `summary` | annonce la fin (contrôlée, voir 5) | `TERMINÉ :` |

Anciens champs acceptés : `chemin→path`, `contenu→content`, `avant→old`,
`apres→new`, `texte→command`, `motif→pattern`. Un message sans JSON mais avec
« TERMINÉ : … » vaut encore `done`.

### 4.2 Plusieurs actions par message

- Jusqu'à `MAX_ACTIONS_PAR_MESSAGE` (10) actions, exécutées dans l'ordre.
- Arrêt à la **première action en erreur** (ou refusée par l'utilisateur) : les
  suivantes sont marquées SKIPPED.
- `plan` peut être n'importe où ; `ask` et `done` ne sont traités que s'ils
  arrivent en dernier et que tout le reste a réussi (sinon SKIPPED).
- Une action dangereuse au milieu d'un lot demande l'accord à ce moment-là.

### 4.3 Le message de résultats renvoyé à Gemini

```
RESULTS
[1] create index.html: OK
index.html created (42 lines)
[2] run "python -m py_compile server.py": ERROR (exit code 1)
  File "server.py", line 3 …
[3] create style.css: SKIPPED (an earlier action failed)
---
Reply with JSON actions only. Finish with {"action": "done", "summary": "…"} once every plan step is [x] and verified.
```

Chaque bloc de résultat est coupé à `TAILLE_MAX_SORTIE`.

### 4.4 Le cadre envoyé avec chaque demande

Chaque message que tu tapes dans une conversation Cowork part ainsi (gabarit
dans `cowork/instructions.py`, généré depuis le catalogue des actions, 4.6) :

```
[AGENT FIRST · COWORK]
You are the Cowork agent of Agent First, running on the user's Windows PC.
You do the work yourself by sending actions; Agent First executes them and
sends back the results. Never tell the user to run something: run it yourself.

HOW TO ANSWER
- Your messages contain ONLY JSON actions (one ```json block: an action
  object or a list of actions). Up to 10 per message, run in order, stopping
  at the first error.
- Write to the user in French inside the actions (plan steps, questions, summary).
- JSON strings: escape " as \", newlines as \n, backslashes as \\.

ACTIONS
<une ligne par action : nom, exemple JSON, effet — depuis le catalogue>

WORKFLOW
1. Plan first: restate the request as concrete steps with "plan".
2. Look before changing: list/read/search what you will touch.
3. Do the steps; resend the plan with [x] as steps get done.
4. Verify: run the code or tests; for a server, start it then visit it. Fix failures.
5. Finish with "done" only when every step is [x] and verified — Agent First
   refuses it otherwise. If the request is unclear, use "ask".

SAFETY
File actions only work inside the working folder. Deletions and risky
commands need the user's approval; Agent First asks for it. If refused,
find another way.

WORKING FOLDER: C:\…\TEST IA   (all paths are relative to it)
FOLDER CONTENT (37 entries):
app/
  controllers/main_controller.py
  …
RUNNING PROCESSES: #1 python server.py (since 10:52)
LAST TASK: <résumé + fichiers changés de la tâche précédente, s'il y en a une>

USER REQUEST:
"""
<ton message, tel quel>
"""
Reply now with your first actions.
```

- Après un `ask`, ton message suivant part avec `USER ANSWER TO YOUR QUESTION:`
  au lieu de `USER REQUEST:`.
- **Contenu du dossier** : 150 entrées au plus, en arborescence, sans `.git`,
  `node_modules`, `__pycache__`, `.venv`/`venv` ; au-delà « … (N more) ».
- Le rappel après un format cassé redonne la liste compacte des actions et, si
  le JSON est abîmé, la règle d'échappement.

### 4.5 Erreurs d'action : jamais de plantage

Toute action produit un résultat OK ou ERROR, jamais d'exception qui remonte :

- champ requis manquant ou action inconnue → `ERROR: missing field "path"` /
  `unknown action "x"` (avec la liste des actions) ;
- fichier ou dossier absent, droits, encodage → `ERROR: <raison>` ;
- `edit` : passage `old` introuvable → ERROR + le **passage le plus proche**
  du fichier (lignes et texte) ; passage trouvé plusieurs fois → ERROR
  « appears N times, include more surrounding lines » ;
- `create` sur un fichier existant → OK, avec le diff ancien/nouveau ;
- `run` qui dépasse le délai → l'**arbre** de processus est tué (aujourd'hui un
  `python` lancé par PowerShell survit) ; « use start for long-running processes ».

### 4.6 Un catalogue unique des actions

`cowork/catalogue.py` décrit chaque action une fois : nom, champs requis et
optionnels, anciens noms, phrase d'aide anglaise, exemple. En découlent :
le mode d'emploi et le rappel (instructions), la lecture et la réparation du
JSON (clés connues), la validation des champs, l'aiguillage de l'exécuteur.
Un test vérifie que chaque action a son libellé dans l'app (`outils_cowork.js`).

## 5. La fin contrôlée et le bilan

### 5.1 Ce qu'est une tâche

Une **tâche** commence avec ta demande et finit par `done` accepté, un arrêt,
une erreur ou la limite d'allers-retours. Un `ask` la **met en pause** : ta
réponse la reprend avec le même plan, les mêmes compteurs et les mêmes effets
(on ne contourne donc pas le contrôle de fin en posant une question). Une
nouvelle demande alors qu'un plan n'était pas fini démarre une nouvelle tâche ;
l'ancien plan apparaît dans `LAST TASK` (étapes non cochées comprises), sans
bloquer.

L'état de la tâche (plan, effets, vérification, relances, pause sur question)
est gardé par conversation et **reconstruit depuis l'historique** au besoin :
une question à laquelle tu réponds après un redémarrage d'Agent First reprend
bien la même tâche.

### 5.2 Le contrôle de fin

Quand Gemini envoie `done` :

1. **Plan non fini** : s'il reste des étapes `[ ]`, Agent First répond
   `NOT FINISHED: unchecked plan steps: … Continue, or resend the plan if they
   are no longer needed.`
2. **Travail non vérifié** : si des fichiers ont été écrits/modifiés/supprimés
   depuis la dernière vérification (`run`, `start` ou `visit`), Agent First
   répond **une seule fois par tâche** `Verify your work first (run it, test it,
   or start + visit a server). If verification makes no sense here, send done
   again.` Les écritures de `.md`/`.txt` seules n'en déclenchent pas.
3. Au plus `RELANCES_FIN_MAX` (2) refus par tâche ; ensuite la fin est acceptée
   et le bilan le signale (« plan non terminé »).
4. Fin acceptée → étape `termine` avec le résumé de Gemini **et** le bilan
   factuel d'Agent First : fichiers créés, modifiés, supprimés (chemins),
   commandes lancées (texte + code de sortie), processus encore actifs.

`ask` → étape `question` : la tâche s'arrête ; l'app affiche la question ; ton
prochain message est sa réponse.

## 6. Processus en arrière-plan (`start` / `logs` / `stop`)

- `start` passe par la même analyse de sûreté que `run`. Agent First lance la
  commande PowerShell dans le dossier, lit sa sortie en continu (tampon borné),
  attend `ATTENTE_DEMARRAGE` (3 s) puis répond : `started #1 (pid 1234)` + la
  sortie déjà produite — ou ERROR + sortie + code si le processus s'est déjà
  arrêté.
- `logs #id` : la sortie produite depuis la dernière lecture. `stop #id` : tue
  l'arbre de processus et renvoie la fin de la sortie.
- Les processus sont rattachés à la conversation et **survivent à la fin de la
  tâche** (le serveur reste utilisable). Au plus `MAX_PROCESSUS` (3) par
  conversation. Tous sont arrêtés quand Agent First s'arrête.
- L'app les montre dans l'en-tête de la conversation, avec un bouton Arrêter.
- `visit` : `http://localhost`, `127.0.0.1` ou `[::1]` seulement (sinon ERROR),
  délai 10 s ; renvoie `HTTP 200 text/html 1234 bytes` + le début du corps.
  Ports **interdits** : ceux d'Agent First (`PORT_AGENT`, `PORT_API`) et celui
  de Chrome (`PORT_CHROME`) — sinon Gemini pourrait valider lui-même une demande
  d'accord ou piloter le Chrome connecté à ton compte Google. GET, POST, PUT,
  DELETE… sont permis sur les autres ports locaux (ses propres serveurs).

## 7. Le rendu visuel (fil Cowork)

Même style sobre (gris chauds, accent terre cuite, monospace pour le technique).
Une maquette sera montrée avant le code.

- **Carte de plan** : une par tâche, mise à jour sur place (cases cochées,
  « 3/5 »), là où le plan a été posé.
- **Étapes** : lignes compactes comme aujourd'hui (point d'état, verbe anglais
  en monospace `Write`/`Edit`/`Run`/`Start`/`Visit`…, chemin, `+12 −3`) ; les
  actions d'un même message sont regroupées ; SKIPPED en gris.
- **Format cassé** : ligne repliable qui montre ce que Gemini a écrit.
- **Fin** : bulle du résumé de Gemini + **carte Bilan** (compteurs, liste des
  fichiers cliquable pour voir le diff, commandes en échec en rouge).
- **Question** : carte avec la question ; le champ de saisie prend le focus.
- **En-tête** : pastille « 1 processus actif » (commande, durée, Arrêter).
- **Accord en attente ailleurs** (tâche lancée par l'API, ou autre conversation
  que celle affichée) : la conversation est marquée dans la barre latérale et
  un bandeau « Une tâche attend ton accord » mène à elle. L'app reçoit pour
  cela un flux d'événements global (`GET /api/evenements`, SSE) ; ouvrir une
  conversation dont la tâche tourne rejoue ses étapes puis suit le direct.
- Les anciennes conversations (noms d'actions français) s'affichent pareil.

## 8. L'API réseau

### 8.1 Écoute et clé

- Second serveur dans le même programme : `HOTE_API = "0.0.0.0"`,
  `PORT_API = 8766`, `API_ACTIVE = True` (dans `config.py`). L'app et ses
  routes `/api/…` restent sur `127.0.0.1:8765`, sans clé, inchangées.
- **Clé obligatoire** sur toutes les routes `/v1/…` : en-tête
  `Authorization: Bearer <clé>`, comparaison en temps constant ; sinon 401.
  Trop d'essais faux depuis une même adresse (10/min) → 429 pendant 1 min.
- La clé est créée au premier lancement (`secrets.token_urlsafe(32)`) dans
  `donnees/cle_api.txt` (déjà exclu de git), affichée dans la console et dans
  **Paramètres** (adresse réseau du PC, clé masquée, Copier, Régénérer).
- Documentation interactive (FastAPI) sur `http://<pc>:8766/docs` ; la lire ne
  demande pas de clé, appeler oui.

### 8.2 Format OpenAI

| Route | Rôle |
|---|---|
| `GET /v1/models` | modèles Gemini (`id` = nom exact, ex. `"4 Argon"`) |
| `POST /v1/chat/completions` | `model`, `messages`, *`stream`*, *`reasoning_effort`* |

- `reasoning_effort` `low`/`medium`/`high` → niveau `Min.`/`Moyen`/`Max.`.
- **Suite de conversation** : un client OpenAI renvoie tout l'historique à
  chaque appel. Agent First garde, pour chaque conversation créée par l'API,
  l'empreinte des messages déjà échangés ; si `messages` moins le dernier
  correspond à une conversation connue, seul le dernier message est envoyé
  dans la même conversation Gemini. Sinon : nouvelle conversation Gemini, avec
  le `system` et les messages précédents mis à plat en un seul texte.
- `stream: true` : réponse en SSE au format OpenAI, en un seul morceau (Gemini
  web est lu à la fin), puis `[DONE]`.
- `usage` : estimation (caractères / 4). `tools`/`functions` : non gérés
  (ignorés).
- Les conversations de l'API apparaissent dans l'historique de l'app, marquées
  « api » (nouvelle colonne `source`, migrée comme les autres).

### 8.3 Routes Cowork (anglais)

| Route | Rôle |
|---|---|
| `POST /v1/cowork` `{folder, request, model?, reasoning_effort?}` | crée la conversation et lance la tâche → `{id}` |
| `POST /v1/cowork/{id}/messages` `{text}` | nouvelle demande ou réponse à une question |
| `GET /v1/cowork/{id}` | état (`queued`, `running`, `waiting_approval`, `question`, `done`, `error`, `stopped`), plan, étapes, résumé, bilan |
| `GET /v1/cowork/{id}/events` (SSE) | étapes en direct, noms anglais |
| `POST /v1/cowork/{id}/decision` `{step, approve, always?}` | accord sur une action dangereuse |
| `POST /v1/cowork/{id}/stop` | arrête la tâche |
| `POST /v1/cowork/{id}/processes/{n}/stop` | arrête un processus lancé |

- `folder` : dossier existant, chemin absolu ; refusé si c'est la racine d'un
  disque ou un dossier système (`C:\Windows`, `Program Files`…).
- `POST /v1/cowork` et `/messages` répondent tout de suite avec l'`id`. Si
  Chrome est occupé (autre tâche, Chat), la tâche est `queued` et démarre à son
  tour ; `GET` et `events` le montrent. Une 2ᵉ demande sur une conversation dont
  la tâche n'est pas finie → 409.
- Les demandes d'accord apparaissent **aussi** dans l'app si elle est ouverte
  (7) : la première réponse (API ou app) l'emporte.
- Les événements internes restent en français (historique) ; une petite
  traduction les présente en anglais à l'API externe.

## 9. Code plus propre

- `cowork/catalogue.py` (nouveau) : la source unique des actions (4.6).
- `cowork/format.py` : `lire_actions(message) -> list[Action]` (blocs, listes,
  alias, réparation) ; résultats et rappels en anglais.
- `cowork/boucle.py` : un objet d'état de tâche (plan, effets, vérification,
  relances) et des étapes nommées (lire → valider → sûreté → exécuter →
  résultats → contrôle de fin), réglages groupés au lieu de 9 paramètres.
- `cowork/actions.py` : aiguillage par le catalogue, toutes les erreurs en
  `Resultat`, effet de chaque action (créé/modifié/supprimé) pour le bilan.
- `cowork/processus.py` (nouveau) : processus en arrière-plan.
- `agent_first/api_reseau.py` (nouveau) : second serveur, clé, routes `/v1`.
- Rien ne change pour le mode Chat de l'app.

## 10. Erreurs

| Situation | Ce qui se passe |
|---|---|
| Réponse hors format | rien d'exécuté ; rappel complet ; texte gardé dans l'étape ; arrêt après 3 d'affilée |
| Action invalide (champ, chemin, fichier) | ERROR renvoyée à Gemini, la tâche continue |
| `done` trop tôt | refusé (5) ; au plus 2 fois par tâche |
| Processus qui meurt au démarrage | ERROR + sa sortie ; Gemini corrige |
| Plus de 3 processus | ERROR « stop one first » |
| `visit` hors localhost | ERROR, rien n'est envoyé |
| Clé absente ou fausse | 401 ; 429 après 10 essais faux/min |
| Chrome occupé, appel `/v1/chat/completions` | attend son tour jusqu'à `DELAI_AGENT`, puis 504 |
| Chrome occupé, `POST /v1/cowork` | tâche `queued`, démarre à son tour |
| Trop d'allers-retours | arrêt après `MAX_TOURS_COWORK` (40) messages à Gemini |

## 11. Tests

- **pytest** : catalogue → instructions (toutes les actions présentes) ; lecture
  de lots, listes, alias français, réparation avec les clés anglaises ; boucle
  avec faux pilote : lot arrêté à la 1ʳᵉ erreur, accord au milieu d'un lot,
  `done` refusé (plan, vérification) puis accepté, `ask`, bilan ; exécuteur :
  fichier absent, champ manquant, `edit` passage proche / multiple, diff de
  réécriture ; processus réels courts (`python -c` qui dort / écrit) : start,
  logs, stop, mort au démarrage, arbre tué ; `visit` sur un petit serveur local
  de test et refus hors localhost ; API : 401/429, `/v1/models`,
  `/v1/chat/completions` (faux pilote, suite de conversation, stream),
  routes Cowork.
- **node --test** : libellés anglais et français, bilan, plan.
- **Réel** (avec ton accord, consomme ton quota Gemini) : dans un dossier
  jetable, les critères 1 à 5 ; depuis un autre appareil du réseau, 6 et 7.

## 12. Hors du périmètre

- Vrai streaming mot à mot (Gemini web est lu à la fin).
- Appels d'outils au format OpenAI (`tools`), images et fichiers joints.
- HTTPS : sur le réseau local, la clé circule en clair (HTTP).
- Plusieurs tâches en parallèle (un seul Chrome).

## 13. À savoir

- Avec l'API réseau, **quiconque a la clé** peut faire agir Cowork sur ton PC
  (avec les mêmes garde-fous et demandes d'accord). Garde la clé pour toi,
  régénère-la au moindre doute.
- Au premier lancement, Windows demandera d'autoriser Python dans le pare-feu
  pour le port 8766 : accepte « réseaux privés » seulement.
- Limite connue, inchangée par cette version : l'API locale de l'app
  (127.0.0.1:8765) n'a pas de clé, donc un programme lancé sur ton PC (y compris
  par une commande « sûre » de Cowork, comme un script Python) pourrait
  l'appeler. `visit` est bloqué sur ce port, mais pas un script. À traiter plus
  tard (jeton de session pour l'app).
