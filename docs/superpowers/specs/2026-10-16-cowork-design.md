# agent.first — modes Chat et Cowork — fiche de conception

Date : 2026-10-16
Statut : à valider
S'ajoute à la v2 (`docs/superpowers/specs/2026-10-15-gemini-agent-first-v2-design.md`) ;
le pilote, la file d'attente, l'historique et l'app web sont gardés.

## 1. But

Donner à l'app deux **modes** de conversation :

- **Chat** : la discussion simple d'aujourd'hui (inchangée).
- **Cowork** : un assistant qui travaille sur le PC comme Claude Code. Il
  lit, crée et modifie des fichiers et des dossiers, cherche dans le code et
  lance des commandes, dans un **dossier de travail** que l'utilisateur
  choisit. C'est toujours Gemini (site web) qui réfléchit ; Agent First est le
  bras qui agit, enchaîne les actions et montre chaque étape en direct.

**Sécurité au cœur du mode** : Cowork agit seul tant que c'est sans risque,
pour rester réactif, mais Agent First **analyse chaque commande et chaque
écriture** et demande l'accord de l'utilisateur dès que l'action est jugée
dangereuse. L'utilisateur garde la main.

**C'est réussi quand :**

1. En mode Cowork, dossier de travail choisi, « Crée une page d'accueil HTML
   et lance-la » aboutit : Gemini fait créer le fichier, le vérifie, et l'app
   affiche chaque étape au fur et à mesure.
2. « Modifie le titre de index.html » montre le fichier avant/après (lignes
   ajoutées et retirées) sans tout réécrire.
3. Une commande sûre (`dir`, `python x.py`) s'exécute sans rien demander ; une
   commande jugée dangereuse (suppression, hors du dossier, commande système,
   `git push`…) s'arrête et attend « Continuer » ou « Refuser », avec la raison
   affichée.
4. Si Gemini se trompe de format d'action, Agent First le lui signale et lui
   redonne le bon format, sans rien exécuter.
5. Une action ne peut pas écrire ni supprimer **en dehors** du dossier de
   travail sans l'accord explicite de l'utilisateur.

## 2. Ce que tu as dit / ce que j'ai supposé

| Point | Source |
|---|---|
| Deux modes : Chat (simple) et Cowork (agent sur le PC) | toi |
| Cowork fait tout de A à Z : commandes, fichiers, dossiers | toi |
| Agent First présente bien les choses pour que Gemini comprenne | toi |
| App réactive, étapes affichées en direct | toi |
| Agent First analyse les commandes ; demande à l'utilisateur si une commande est jugée dangereuse | toi |
| Pas de demande pour les actions sûres (lecture, écriture dans le dossier, commandes sûres) | hypothèse (validée « oui go ») |
| Dossier de travail choisi par conversation Cowork | hypothèse |
| Toute action hors du dossier de travail passe par l'accord de l'utilisateur | hypothèse |
| Les réponses de Gemini en mode Cowork portent des actions dans un format fixe | hypothèse |

## 3. Comment Agent First parle à Gemini (le cœur du mode)

Gemini web n'est pas prévu pour piloter un PC : tout repose sur un cadrage
clair et un format d'action strict.

### 3.1 Le mode d'emploi (premier message d'une conversation Cowork)

Au début d'une conversation Cowork, Agent First envoie à Gemini un message
d'instructions en français (gabarit dans `cowork/instructions.py`) :

- **Rôle** : « Tu es l'assistant d'Agent First. Tu travailles dans le dossier
  `<chemin>`. Pour agir, tu demandes **une seule action à la fois** dans le
  format ci-dessous ; Agent First l'exécute et te renvoie le résultat. »
- **Liste des actions** (voir 3.2) avec, pour chacune, à quoi elle sert.
- **Format exact** : un bloc de code `json` contenant un objet
  `{"action": "...", ...}` et **rien d'autre** dans le message quand une action
  est demandée ; une phrase normale (sans bloc) quand c'est fini.
- **Règles** : une action par message ; rester dans le dossier de travail ;
  attendre le résultat avant la suivante ; dire « TERMINÉ : <résumé> » à la fin.
- **Un exemple complet** d'un aller-retour (action → résultat → action → fin).

### 3.2 Les actions (format JSON, lues par Agent First)

| action | champs | ce qu'elle fait |
|---|---|---|
| `lister` | `chemin` | liste un dossier |
| `lire` | `chemin` | lit un fichier (coupé si très long) |
| `chercher` | `motif`, `glob?` | cherche un texte dans les fichiers |
| `creer` | `chemin`, `contenu` | crée ou réécrit un fichier |
| `modifier` | `chemin`, `avant`, `apres` | remplace un passage exact par un autre |
| `supprimer` | `chemin` | supprime un fichier ou un dossier |
| `commande` | `texte` | lance une commande PowerShell |

- Les chemins sont relatifs au dossier de travail. Un chemin absolu ou qui
  « remonte » hors du dossier (`..`) est **hors périmètre** → accord requis.
- Agent First renvoie à Gemini un bloc court : `OK` + le résultat utile (sortie,
  extrait, diff), ou `ERREUR : <raison>`. Les sorties longues sont coupées avec
  « …(coupé) ».

### 3.3 Quand Gemini se trompe

Si le message de Gemini ne contient pas de bloc d'action lisible (format cassé,
action inconnue, champs manquants), Agent First n'exécute rien et renvoie :
« Format non compris. Rappel du format : … » avec le gabarit. Après plusieurs
échecs d'affilée (3), la conversation s'arrête avec un message clair dans l'app.

## 4. L'analyse de sûreté (le garde-fou)

Avant d'exécuter une `commande`, une `supprimer`, ou une écriture (`creer`,
`modifier`), Agent First la classe (`cowork/surete.py`) :

- **Sûre** → exécutée directement. Exemples : lecture, écriture **dans** le
  dossier de travail, commandes de lecture/build courantes
  (`dir`, `ls`, `type`, `cat`, `git status`, `git diff`, `python`, `node`,
  `npm test`, `npm run`, `pytest`…).
- **Dangereuse** → l'app demande « Continuer » / « Refuser » avec la raison.
  Déclencheurs :
  - toute **suppression** ;
  - tout chemin **hors du dossier de travail** (absolu ou `..`) ;
  - **commandes système** : `Remove-Item -Recurse`/`-Force`, `rd`/`del` en
    masse, `Format-*`, `Stop-Computer`/`Restart-Computer`, services
    (`Stop-Service`, `sc`), registre (`reg`, `Set-ItemProperty HKLM:`…),
    tâches planifiées, pare-feu, droits (`icacls`, `takeown`), `runas`/élévation ;
  - **réseau + exécution** : télécharger puis exécuter (`Invoke-WebRequest`/`curl`
    suivis d'un lancement), `Invoke-Expression` sur du contenu distant ;
  - **publication/sortie** : `git push`, envoi vers un service externe ;
  - **installations** : `pip install`, `npm install -g`, `winget`, `choco`,
    `msiexec` ;
  - toute commande **non reconnue** (par prudence : inconnu = demande).
- Un même risque autorisé une fois peut être mémorisé « pour cette
  conversation » (case « Toujours autoriser ce type ici »), jamais au-delà.

La classification est **prudente** : en cas de doute, c'est « dangereuse ». La
liste est dans un seul fichier, pour l'ajuster facilement. Ce garde-fou protège
des mauvaises actions que Gemini pourrait proposer, surtout après avoir lu un
fichier ou une page qui l'influence.

## 5. Architecture (ajouts à la v2)

```
App web ──mode + dossier──▶ Agent First ──▶ Pilote Cowork ──▶ Gemini (site)
   ▲  étapes en direct (SSE)      │  boucle d'actions          │
   │                              ▼                            │ action JSON
   │                       cowork/ : instructions, analyse      ▼
   └──── accord (dangereux) ◀──── exécution (fichiers, cmd) ◀── Agent First
```

- **`cowork/` (nouveau paquet)** :
  - `instructions.py` : le mode d'emploi envoyé à Gemini.
  - `actions.py` : lecture/écriture de fichiers et exécution de commandes,
    **toujours bornées au dossier de travail** (un chemin hors périmètre est
    refusé au niveau du code, pas seulement signalé).
  - `surete.py` : la classification sûre/dangereuse.
  - `format.py` : lire le bloc d'action JSON du message de Gemini ; fabriquer le
    bloc de résultat renvoyé à Gemini.
  - `boucle.py` : l'enchaînement « action → exécution (ou accord) → résultat →
    Gemini » jusqu'à « TERMINÉ », avec un nombre maximal d'étapes.
- **Pilote** : `PiloteGemini.envoyer` est déjà là ; Cowork l'appelle en boucle
  (même conversation Gemini), en lui passant à chaque tour le résultat de
  l'action précédente comme message.
- **Agent First** : nouvelles routes pour Cowork (voir 6), et **flux en direct**
  (SSE) pour pousser chaque étape à l'app sans attendre la fin.
- **Historique** : une conversation retient son `mode` (`chat`/`cowork`) et son
  `dossier` ; chaque étape est un message (`type` : action, résultat, diff,
  commande, erreur, demande d'accord) pour pouvoir la rouvrir.

## 6. API (ajouts)

| Route | Rôle |
|---|---|
| `POST /api/conversations` `{mode, dossier?, modele?, niveau?}` | crée une conversation Chat ou Cowork |
| `POST /api/cowork/{id}/messages` `{texte}` | lance la tâche ; les étapes arrivent par le flux |
| `GET /api/cowork/{id}/flux` (SSE) | étapes en direct : action, résultat, diff, demande d'accord, terminé |
| `POST /api/cowork/{id}/decision` `{etape, reponse, toujours?}` | « continuer »/« refuser » sur une action dangereuse |
| `POST /api/cowork/{id}/arreter` | stoppe la tâche en cours |
| `POST /api/dossiers/choisir` | ouvre un sélecteur de dossier Windows et renvoie le chemin |

Le mode Chat garde ses routes v2.

## 7. L'app (ajouts)

- **Bascule Chat / Cowork** en haut de la discussion. En Cowork, une ligne
  « Dossier : … » avec un bouton pour le choisir (obligatoire avant d'envoyer).
- **Fil Cowork** : chaque étape est une carte (créé / modifié / commande / lu /
  cherché), avec icône, chemin, et pour `modifier` le diff (vert/rouge). La
  sortie des commandes est repliable.
- **Demande d'accord** : carte rouge « Commande jugée dangereuse », la commande,
  la raison, et « Refuser » / « Continuer » (+ « Toujours autoriser ce type
  ici »). La tâche attend ; la pastille passe à « En attente de ta décision ».
- **Réactivité** : les étapes s'affichent au fil de l'eau (flux SSE) ; bouton
  **Arrêter** pendant une tâche ; une commande longue montre « En cours… ».
- **Reprise** : rouvrir une conversation Cowork réaffiche ses étapes et son
  dossier (lecture seule du passé ; un nouveau message relance la boucle).

## 8. Erreurs

| Situation | Ce qui se passe |
|---|---|
| Dossier non choisi (Cowork) | envoi bloqué, invite à choisir le dossier |
| Action hors du dossier de travail | refusée par le code → demande d'accord, ou erreur si refusée |
| Format d'action cassé | non exécuté ; rappel du format à Gemini ; arrêt après 3 échecs |
| Commande qui dépasse un délai | coupée ; « commande trop longue » renvoyé à Gemini |
| Trop d'étapes (garde-fou de boucle) | arrêt ; « limite d'étapes atteinte » dans l'app |
| Refus d'une action dangereuse | l'action est abandonnée ; Gemini en est informé et continue autrement |

## 9. Tests

- **Automatiques (pytest)** : analyse de sûreté (nombreux cas sûrs/dangereux,
  chemins hors périmètre), lecture du format d'action (valide, cassé, inconnu),
  bornage des chemins au dossier de travail, boucle avec un **faux pilote**
  (enchaînement, demande d'accord, refus, limite d'étapes) et un **faux
  exécuteur** (aucun vrai fichier touché).
- **Réel** : un script qui fait faire à Gemini, dans un dossier jetable, une
  petite tâche (créer un fichier, le relire, lancer `dir`) et une commande
  dangereuse pour vérifier la demande d'accord.
- **App** : les 5 critères de la section 1, dans un dossier de test.

## 10. Fichiers

```
cowork/        instructions.py, actions.py, surete.py, format.py, boucle.py
agent_first/   serveur.py (+ routes et flux Cowork), historique.py (+ mode, dossier, type d'étape)
agent_first/web/  app.js/app.css/index.html (+ bascule de mode, fil Cowork, demande d'accord)
tests/         test_surete.py, test_format.py, test_actions.py, test_boucle.py, test_cowork_api.py
config.py      délai de commande, nombre max d'étapes, taille max de sortie
```

## 11. Hors du périmètre (première version)

- Exécuter plusieurs commandes en parallèle.
- Un bac à sable complet (Cowork agit avec les droits de l'utilisateur).
- Cowork hors de Windows / PowerShell.
- Annuler automatiquement ce qu'une étape a fait (pas de « défaire »).
- Deux tâches Cowork en même temps (un seul Chrome, une seule à la fois).

## 12. À savoir

- Cowork agit **avec tes droits** sur ton PC : l'analyse de sûreté et tes accords
  sont la protection, il n'y a pas de bac à sable. À utiliser dans un dossier de
  travail choisi, pas à la racine du disque.
- Gemini peut proposer une mauvaise action, surtout après avoir lu un fichier ou
  une page qui l'influence : c'est justement pourquoi les actions dangereuses
  demandent ton accord, et pourquoi tout est borné au dossier de travail.
- Les commandes et leurs sorties passent par la mémoire d'Agent First et par la
  conversation Gemini (donc par Google) : ne fais pas manipuler à Cowork des
  secrets (mots de passe, clés) que tu ne veux pas voir partir chez Google.
