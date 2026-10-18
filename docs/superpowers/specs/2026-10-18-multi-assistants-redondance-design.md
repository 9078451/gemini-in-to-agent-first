# agent.first — plusieurs assistants et redondance — fiche de conception

Date : 2026-10-18
Statut : réalisé ; repères de ChatGPT, Claude, Le Chat, DeepSeek et Grok à
confirmer en essai réel (voir 7)
S'ajoute à la fiche « fichiers joints, réponse en direct, arrêt » (2026-10-18).

## 1. Pourquoi

- Agent First ne savait piloter que Gemini. Quand Gemini est saturé (« forte
  demande ») ou que le compte a épuisé ses messages, il n'y avait rien d'autre à
  faire qu'attendre.
- La demande : faire pour ChatGPT, Claude et d'autres assistants la même chose
  que pour Gemini (même principe : piloter le site dans le Chrome dédié), et une
  option **Redondance** : un assistant trop sollicité ou sans crédit passe la
  main à un autre ; sans l'option, l'app propose les autres et l'utilisateur
  choisit.

## 2. Critères de réussite

1. App : choisir l'assistant et son modèle (menu rangé par assistant, puces sur
   une conversation vide) ; changer d'assistant en cours de conversation, le
   nouveau recevant l'historique.
2. Sans redondance : une erreur « saturé / limite / pas connecté / pas de
   réponse » propose **Avec ChatGPT**, **Avec Claude**… (et Réessayer).
3. Avec redondance : relais automatique dans l'ordre réglé, en direct (« Gemini
   est indisponible : ChatGPT prend le relais »), noté dans l'historique ; la
   conversation reste ensuite chez le nouvel assistant.
4. Créer : seuls les assistants qui savent créer le média le reçoivent (menu
   grisé, relais filtré).
5. API : le nom du modèle choisit l'assistant (`gpt-5`, `chatgpt/Thinking`,
   `claude-opus-4-1`…), `provider` le force, `redundancy` active le relais pour
   un appel ; réponse `provider` ; 429 si saturé sans relais.
6. Arrêter une réponse ne déclenche jamais le relais.

## 3. Un profil par site (`pilote/sites.py`)

Le pilote de Gemini devient générique : `PiloteGemini` (alias `PiloteWeb`) prend
un `Site` qui regroupe tout ce qui dépend de la page — adresse, préfixe des
onglets, **repères** (sélecteurs CSS par rôle : saisie, envoyer, arrêter,
question, réponse, bouton des modèles…), zone de saisie, façon de joindre,
menus des outils et des modèles, décor à retirer de la réponse, phrases de
limite. Profils : Gemini (vérifié), ChatGPT, Claude, Le Chat, DeepSeek, Grok.

- **Modèles** : Gemini garde son menu à deux niveaux (`pilote/modes.py`) ; les
  autres ont une liste simple (`pilote/modes_menu.py`) : un bouton, une option
  par modèle (nom, puis description). « Sonnet » choisit « Claude Sonnet 4.5 »
  (tous les mots contenus, une seule option). Pas de niveau séparé.
- **Limite** : la réponse (courte, pas une citation de la question) qui dit
  « usage limit », « high demand », « at capacity », « crédits épuisés »… lève
  `LimiteAtteinte`. Gemini garde aussi son bandeau (`LimiteGemini`).
- **Connexion** : chaque site a ses adresses de connexion et de vérification ;
  `PasConnecte` / `VerificationRequise` nomment le compte (« Connecte-toi à
  ChatGPT dans la fenêtre Chrome dédiée »).

## 4. Fournisseurs et redondance (`agent_first/envoi.py`)

- `Fournisseur` : un site, sa file (une fenêtre du Chrome dédié), ses modèles.
  Gemini garde ses deux fenêtres (Chat, Cowork) ; les autres en ont une, ouverte
  **au premier message** qui leur est destiné (`CacheModes` paresseux : la liste
  par défaut de `config.MODELES_SITES` sert jusque-là).
- La conversation a un `fournisseur` (colonne ajoutée à l'historique). Changer
  d'assistant (`historique.basculer`) efface l'adresse : le prochain message part
  dans une nouvelle conversation chez lui, précédé de la **transcription** des
  échanges (« [Conversation so far — you are taking over…] », les 16 000 derniers
  caractères).
- `Repartiteur.deroulement` : essaie l'assistant de la conversation puis, avec la
  redondance, les suivants de l'ordre réglé qui savent faire la demande. Bascule
  sur `LimiteAtteinte`, pas connecté, vérification, repère introuvable, message
  non envoyé ou abandonné, délai, pièce refusée, page instable, modèle
  introuvable. Pas sur `ChromeInjoignable` (Chrome est le même pour tous), ni sur
  une erreur inattendue, ni après **Arrêter**. L'essai abandonné reçoit l'arrêt
  (s'il écrit encore) et sa réponse tardive n'est pas gardée.
- Évènements : `texte` (direct), `relais` (de, vers, raison), `fin`. Partagé par
  l'app (NDJSON) et l'API (SSE).
- `ReglagesApp` (`donnees/reglages.json`) : `redondance` et `ordre`, communs à
  l'app et à l'API. Un nom inconnu est retiré ; un assistant oublié va à la fin.

## 5. App

- `GET /api/fournisseurs` (assistants, outils, modèles), `GET/POST /api/reglages`,
  `POST /api/conversations/{id}/fournisseur`, `fournisseur` à la création.
- Message : ligne `relais` en direct, note « relais » gardée ; erreur 429 pour
  une limite ; `autres` (assistants à proposer) quand la redondance est
  désactivée et que l'erreur permettrait le relais.
- Interface : menu des modèles par assistant (point de connexion, ce qu'il sait
  créer, interrupteur Redondance en bas) ; puces d'assistant sur une
  conversation vide ; textes au nom de l'assistant (« Demande à ChatGPT… »,
  « Claude réfléchit… ») ; options de Créer grisées ; Paramètres : assistant par
  défaut, Redondance, ordre (↑ ↓), état de chaque compte ; export et historique
  nomment l'assistant.

## 6. API réseau

- `model` → assistant : préfixe `chatgpt/…`, `claude/…`, ou nom à la façon de leur
  API (`gpt-`, `o3`, `claude-`, `mistral-`, `deepseek-`, `grok-`). Le modèle est
  cherché chez l'assistant : nom exact, sinon celui qui contient le plus de mots
  de la demande (« claude-opus-4-1 » → « Opus 4.1 ») ; sinon son modèle courant.
  Un assistant désactivé laisse la main à Gemini (comme avant pour « gpt-4o »).
- `/v1/models` liste aussi `chatgpt/Thinking`, `claude/Opus 4.1`, `chatgpt`…
- `provider`, `redundancy` sur chat, images, médias ; `provider` sur Cowork. Une
  création impossible chez l'assistant choisi → 400 qui nomme ceux qui savent.
- Réponse : `provider` (aussi dans chaque morceau du flux) ; un relais en flux
  ajoute « — ChatGPT prend le relais — » au texte déjà envoyé.

## 7. À confirmer en essai réel

Les repères des cinq nouveaux sites sont relevés d'après leur page publique et
vérifiés sur des pages factices (`tests/test_pilote_page.py`) ; ils peuvent
différer selon le compte et changer sans prévenir. Pour chacun :
`python -m pilote.inspecter --site <nom>` puis
`python -m pilote.essai "Bonjour" --site <nom>` ; corriger `pilote/sites.py`.
Automatiser ces sites peut aller contre leurs conditions d'utilisation : avec
son propre compte, à son rythme.

## 8. Limites connues

- Cowork n'a pas de relais : une tâche reste chez l'assistant choisi à sa
  création.
- La transcription ne transmet pas les fichiers joints des messages précédents
  (seulement ceux du nouveau message).
- Le relais repart de zéro chez le nouvel assistant : le début écrit par le
  précédent est abandonné (l'app l'efface, le flux de l'API l'a déjà envoyé et
  le sépare par une ligne).
