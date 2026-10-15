# Gemini web ↔ Agent First — fiche de conception

Date : 2026-10-15
Statut : à valider

## 1. But

Écrire un message dans une fenêtre (programme GUI sur mesure) et recevoir la
réponse de Gemini **sans passer par l'API** : le programme principal
**Agent First** pilote un vrai Chrome connecté à ton compte Google, tape le
message sur `gemini.google.com`, attend la fin de la réponse, la lit et la
renvoie à la fenêtre. Les messages suivants continuent la même conversation
Gemini.

**C'est réussi quand :**

1. Tu tapes « Bonjour » dans la fenêtre GUI, et la réponse de Gemini s'y
   affiche quelques secondes plus tard.
2. Un deuxième message continue la même conversation (Gemini se souvient du
   premier).
3. Le bouton « Nouvelle conversation » repart d'une conversation vide.
4. Si quelque chose ne va pas (pas connecté à Google, Chrome fermé, Gemini
   trop long), la fenêtre affiche un message clair au lieu de rester bloquée.

## 2. Ce que tu as dit / ce que j'ai supposé

| Point | Source |
|---|---|
| Gemini utilisé par le site web, comme dans Chrome | toi |
| Une plateforme externe envoie les messages à Agent First | toi |
| La plateforme externe = un programme GUI fait sur mesure | toi |
| Agent First ouvre un navigateur dédié, tape, lit, interagit | toi |
| Le programme GUI est créé dans ce projet | hypothèse |
| « Interagir » = continuer la conversation | hypothèse |
| Tout tourne sur ton PC Windows | hypothèse |

## 3. Approches envisagées

1. **Recommandée — vrai Chrome + Playwright branché dessus.** Agent First lance
   ton Chrome installé avec un **profil dédié** (dossier séparé de ton Chrome
   habituel). Tu t'y connectes à Google **une seule fois, à la main**. Ensuite
   Playwright se branche sur ce Chrome (port local de débogage) pour taper et
   lire. Pour Google, c'est un Chrome normal : la connexion est acceptée.
2. **Playwright lance son propre navigateur.** Plus simple, mais Google bloque
   souvent la connexion (« ce navigateur n'est peut-être pas sécurisé »).
   Écartée.
3. **API officielle Gemini.** Plus stable, mais ce n'est pas le web. Écartée
   par ton choix. Le pilote est isolé derrière une interface simple, donc on
   pourra le remplacer par l'API plus tard si le web devient trop fragile.

## 4. Architecture

```
┌──────────────────────┐   HTTP local    ┌────────────────────────┐
│  Programme GUI       │ ──────────────▶ │  Agent First           │
│  (fenêtre)           │ ◀────────────── │  serveur 127.0.0.1:8765│
└──────────────────────┘    réponse      │  + file d'attente      │
                                         │  + mémoire conversations│
                                         └───────────┬────────────┘
                                                     │ un message à la fois
                                         ┌───────────▼────────────┐
                                         │  Pilote navigateur     │
                                         │  (Playwright)          │
                                         └───────────┬────────────┘
                                                     │ port 9222 (local)
                                         ┌───────────▼────────────┐
                                         │  Chrome dédié          │
                                         │  gemini.google.com     │
                                         └────────────────────────┘
```

Trois programmes séparés, chacun avec un seul rôle :

### 4.1 Programme GUI (`gui/`)

- Fenêtre CustomTkinter : zone de conversation (tes messages et ceux de
  Gemini), champ de saisie, bouton **Envoyer**, bouton
  **Nouvelle conversation**, ligne d'état (« Gemini écrit… », erreurs).
- Envoie chaque message à Agent First par HTTP, dans un fil séparé pour que la
  fenêtre ne gèle pas. Le bouton Envoyer est grisé pendant l'attente, qui dure
  au plus 5 minutes (file d'attente + délai Gemini).
- Ne connaît ni Chrome ni Gemini : il ne parle qu'à Agent First.
- **Style visuel** (d'après l'image de référence fournie) : thème sombre
  quasi noir, barre latérale à gauche (logo `agent.first` avec le point en
  vert, bouton « Nouvelle conversation », sections en petites capitales grises
  « CONVERSATION » et « ÉTAT » avec un point de couleur par élément : Agent
  First, Chrome dédié, compte Google), grand titre centré « Discute avec
  **Gemini** » (Gemini en vert), conversation dans une grande carte arrondie
  bordée d'un trait fin, barre de saisie en forme de pilule avec un bouton
  rond « → », pastille blanche d'état en bas à droite (« Prêt ● »). Accent
  vert `#2fd99b`, cartes `#17171a`, texte blanc et gris.

### 4.2 Agent First (`agent_first/`)

- Petit serveur HTTP (FastAPI) qui n'écoute **que sur ton PC**
  (`127.0.0.1:8765`) :
  - `POST /message` `{conversation, texte}` → `{conversation, reponse}`
    ou `{erreur}`
  - `POST /conversations` → crée une conversation, renvoie son identifiant
  - `GET /etat` → Chrome joignable ? connecté à Google ?
- **File d'attente** : un seul Chrome, donc un seul message traité à la fois ;
  les autres attendent leur tour.
- **Mémoire des conversations** (`donnees/conversations.json`) : identifiant
  local → adresse de la conversation Gemini (`gemini.google.com/app/<id>`).
- Ne sait pas comment Gemini fonctionne : il appelle le pilote via une seule
  fonction `envoyer(adresse_conversation, texte) -> (reponse, adresse)`.

### 4.3 Pilote navigateur (`pilote/`)

- `chrome.py` : si Chrome dédié n'est pas lancé, le démarre
  (`chrome.exe --remote-debugging-port=9222 --user-data-dir=profil-chrome-gemini`),
  puis Playwright s'y branche.
- `gemini.py` : ouvre la bonne conversation (ou une nouvelle), tape le texte,
  clique sur Envoyer, attend la fin de la réponse, lit le texte de la dernière
  réponse et renvoie l'adresse de la conversation.
- **Fin de réponse détectée quand** le bouton « Arrêter » a disparu **et** le
  texte n'a plus bougé pendant 2 secondes. Délai maximum : 180 s.
- La réponse est lue en **texte brut tel qu'affiché** : les retours à la ligne
  des listes et du code sont gardés, la mise en forme (gras, titres) non.
- `selecteurs.py` : **tous** les repères de la page Gemini (champ de saisie,
  bouton Envoyer, bloc réponse…) dans ce seul fichier. Quand Google change son
  site, c'est le seul fichier à corriger. Ces repères seront relevés sur la
  vraie page au début de la phase 1.

## 5. Déroulé d'un message

1. Tu écris dans le GUI → `POST /message`.
2. Agent First met le message dans la file d'attente.
3. À son tour, le pilote ouvre la conversation Gemini (adresse mémorisée, ou
   nouvelle conversation).
4. Il tape le message et l'envoie.
5. Il attend la fin de la réponse et lit son texte.
6. Agent First mémorise l'adresse de la conversation et renvoie la réponse.
7. Le GUI l'affiche.

## 6. Erreurs

| Situation | Ce qui se passe |
|---|---|
| Agent First pas lancé | GUI : « Agent First n'est pas démarré » |
| Chrome dédié fermé | relancé automatiquement au message suivant |
| Pas connecté à Google | GUI : « Connecte-toi à Google dans la fenêtre Chrome dédiée » |
| Vérification Google / captcha | **pas contournée** : GUI te demande de la faire toi-même dans Chrome |
| Gemini dépasse 180 s | GUI : erreur + le début de réponse déjà lu |
| Repère de page introuvable | GUI : « Gemini a peut-être changé son interface » + capture d'écran dans `journaux/` |

Tout est noté dans `journaux/agent_first.log`.

## 7. Tests

- **Automatiques (pytest)** : file d'attente, routes HTTP et mémoire des
  conversations, avec un **faux pilote** (pas besoin de Chrome ni de Gemini).
- **Pilote réel** : script d'essai `python -m pilote.essai "Bonjour"` qui
  envoie un vrai message à Gemini et affiche la réponse.
- **De bout en bout, à la main** : les 4 critères de la section 1.

## 8. Organisation des fichiers

```
agent_first/   serveur.py, file_attente.py, conversations.py
pilote/        chrome.py, gemini.py, selecteurs.py, essai.py
gui/           app.py, client.py
tests/
donnees/       conversations.json        (créé au lancement)
journaux/      logs et captures d'écran  (créé au lancement)
profil-chrome-gemini/  profil Chrome dédié (créé au lancement, à ne pas partager)
config.py      ports, délais, chemin de Chrome
demarrer.bat   lance Agent First puis le GUI
requirements.txt  playwright, fastapi, uvicorn, customtkinter, httpx, pytest
.gitignore     exclut profil-chrome-gemini/, donnees/, journaux/
```

## 9. Ordre de construction

1. **Pilote navigateur seul** + script d'essai (la partie la plus risquée).
2. **Agent First** : serveur, file d'attente, mémoire, tests avec faux pilote.
3. **Programme GUI** branché sur Agent First.
4. **Erreurs et finitions** : messages clairs, `demarrer.bat`.

## 10. Hors du périmètre (première version)

- Envoyer des fichiers ou des images, choisir le modèle Gemini.
- Affichage de la réponse mot à mot pendant qu'elle s'écrit.
- Liste des anciennes conversations dans le GUI.
- Plusieurs Chrome en parallèle, utilisation depuis un autre ordinateur.

## 11. À savoir

- Les conditions d'utilisation de Google n'autorisent pas forcément le
  pilotage automatique de l'interface web de Gemini. Ton compte est concerné :
  à utiliser avec modération, pour ton usage personnel.
- Le port 9222 permet à n'importe quel programme de ton PC de piloter le
  Chrome dédié. Il n'est pas ouvert sur le réseau. N'utilise ce profil
  que pour Gemini.
- Le dossier `profil-chrome-gemini/` contient ta session Google : ne le
  partage pas et ne le mets pas sur GitHub.
