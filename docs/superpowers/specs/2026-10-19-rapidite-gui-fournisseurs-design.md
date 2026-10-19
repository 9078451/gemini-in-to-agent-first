# agent.first — rapidité, interface épurée, autres fournisseurs d'IA — fiche de conception

Date : 2026-10-19
Statut : plan et maquette validés (19/10) ; l'utilisateur ajoute les sites web
ChatGPT et Claude.ai pilotés avec ses comptes, en plus des clés API.

## 1. Pourquoi

Mesures du 19/10 (copie de l'historique de l'utilisateur, faux Gemini) :

- l'app locale répond en 2 à 11 ms par appel (conversation de 213 messages
  comprise) : **le temps se perd chez Gemini web** ;
- le journal montre surtout trois pannes : **limite du compte Gemini atteinte**,
  délai dépassé, réponse introuvable ;
- le Chat n'affiche rien tant que la réponse n'est pas finie ;
- `/api/etat` (toutes les 30 s) passe par la file du Chat : derrière un long
  message, il attend jusqu'à 5 s en tenant un fil du serveur ;
- les envois longs et les flux SSE tiennent chacun un fil du serveur (40 par
  défaut) : plusieurs fenêtres ouvertes peuvent figer l'app ;
- chaque vérification du pilote (toutes les 0,3 à 0,5 s) fait 4 à 6 allers-retours
  avec Chrome.

## 2. But et critères de réussite

1. **Rapide** : le texte de la réponse s'affiche pendant qu'il s'écrit (Chat de
   l'app, `stream: true` de l'API réseau) ; une vérification du pilote = un seul
   aller-retour avec Chrome ; l'état ne fait plus la queue.
2. **Stable** : l'app ne se fige pas (fils du serveur élargis) ; un flux Cowork
   coupé se reconnecte ; la base SQLite passe en WAL ; un fournisseur en panne
   ou à sa limite peut être relayé par un **fournisseur de secours**.
3. **Interface épurée et pro** (maquette validée) : style actuel gardé (gris
   chauds, un seul accent terre cuite #d97757, monospace pour le technique).
4. **Autres fournisseurs** :
   - par **clé API** : Claude (Anthropic), OpenAI, Mistral, Groq, OpenRouter,
     DeepSeek, xAI, Gemini API (Google AI Studio), **Ollama** sur ce PC (gratuit,
     sans clé) et un serveur « compatible OpenAI » au choix (LM Studio…) ;
   - par **site web**, dans le Chrome dédié, avec les comptes de l'utilisateur :
     **ChatGPT** (chatgpt.com) et **Claude.ai**, comme Gemini.
   Chat, Cowork et l'API réseau marchent avec chacun.

**C'est réussi quand :**

- un message du Chat montre le début de la réponse en moins d'une seconde après
  que le fournisseur a commencé à écrire ; le bouton Arrêter coupe la réponse et
  garde ce qui est écrit ;
- `/api/etat` répond en moins de 50 ms pendant qu'une réponse s'écrit ;
- avec le secours activé, un message refusé pour limite ou panne repart chez le
  fournisseur de secours, avec l'historique, et la réponse dit « secours » ;
- une clé API saisie dans Paramètres n'est jamais renvoyée en clair à la page ;
- les tests existants passent toujours, avec de nouveaux tests pour chaque partie.

## 3. Non-buts

- Pas de pièces jointes (images, fichiers) dans le Chat.
- Pas de choix du modèle sur Claude.ai (le site garde le sien) ; sur ChatGPT, le
  modèle passe par l'adresse (`?model=`), au mieux.
- Pas de thème clair.
- Pas de chiffrement des clés : elles restent dans `donnees/` (hors git), comme
  la clé de l'API réseau.

## 4. Architecture

```
            app (127.0.0.1:8765)        API réseau (:8766)
                     │                         │
                     ▼                         ▼
              ServiceChat (agent_first/discussion.py)      ServiceCowork
       historique à plat si le fournisseur change ; secours ; états
                     │                         │
                     ▼                         ▼
              Repartiteur (fournisseurs/repartiteur.py)
     ┌───────────────┬───────────────┬───────────────┬────────────────────┐
     │ gemini        │ chatgpt       │ claude_web    │ API (anthropic,     │
     │ FileAttente   │ FileAttente   │ FileAttente   │ openai, ollama…)    │
     │ chat + cowork │ chat + cowork │ chat + cowork │ FileParallele (8)   │
     │ PiloteGemini  │ PiloteSite    │ PiloteSite    │ PiloteAPI…          │
     └───────────────┴───────────────┴───────────────┴────────────────────┘
          un onglet par file, dans le même Chrome dédié     HTTP + flux SSE
```

- **Un pilote par fournisseur, même contrat** (`pilote/modeles.Pilote`) :
  `envoyer(adresse, texte, modele, niveau, delai, au_fil)` → `ResultatGemini`.
  `au_fil(texte, html)` reçoit le texte partiel ; s'il lève `Interrompu`, le
  pilote arrête la réponse (clic sur « Arrêter » du site, ou fermeture du flux
  HTTP) et l'exception remonte avec le texte partiel.
- **Adresse** : pour un site, l'URL de la conversation ; pour une API,
  `api:<uuid>`, dont la transcription est gardée dans `donnees/fils.db`.
- **Conversation** : nouvelles colonnes `fournisseur` (conversation : celui de
  l'adresse ; message : celui qui a répondu). Quand le fournisseur demandé n'est
  pas celui de l'adresse, le premier message part « à plat » (historique +
  nouveau message, format de `openai_compat.mettre_a_plat`) dans une conversation
  neuve chez le nouveau fournisseur.
- **Secours** (`donnees/fournisseurs.json`, réglé dans Paramètres et dans le
  menu des modèles) : `{actif, fournisseur, modele}`. Déclenché par les erreurs
  marquées `secours = True` (limite, Chrome injoignable, pas connecté,
  vérification, message non envoyé/abandonné, délai dépassé, repère introuvable,
  clé refusée, fournisseur indisponible ou à sa limite) — pas par un modèle ou
  niveau introuvable. La conversation continue ensuite chez le secours. En
  Cowork : la tâche continue chez le secours, qui reçoit à plat les échanges de
  la tâche ; un évènement `secours` s'affiche dans le fil.
- **États des fournisseurs** : notés à chaque réponse ou erreur (prêt, limite
  jusqu'à…, déconnecté, en panne) ; `/api/etat` les renvoie sans attendre. L'état
  de Google n'est relu dans l'onglet que si sa file est libre et l'état vieux de
  plus de 60 s.
- **Réponses en Markdown** (API) : converties en HTML par `markdown-it-py`, puis
  nettoyées par `nh3` comme celles de Gemini.
- **Claude par clé API** : SDK officiel `anthropic` (fichier à part),
  `client.messages.stream`, `max_tokens` 64000, réflexion adaptative par défaut ;
  niveau → `output_config.effort` (Min. → low, Moyen → medium, Max. → high) ;
  `stop_reason == "refusal"` → message clair. Modèle par défaut
  `claude-opus-5-5` ; proposés : `claude-opus-5-5`, `claude-sonnet-5-5`,
  `claude-haiku-5-5`.
- **Compatibles OpenAI** : un seul client `httpx`, `POST {base}/chat/completions`
  avec `stream: true` ; `reasoning_effort` envoyé seulement aux fournisseurs qui
  l'acceptent (OpenAI, Gemini API, xAI). Liste des modèles par `GET {base}/models`
  (filtrée : pas d'embeddings, audio, images, modération).
- **Reprises** : 429 et 5xx réessayés 2 fois (1 s puis 3 s, ou `retry-after`
  plafonné à 10 s) avant toute réponse partielle ; jamais après.
- **Sites ChatGPT et Claude.ai** : `PiloteSite` générique + un profil par site
  (repères CSS à plusieurs candidats, comme `pilote/selecteurs.py`). Ils
  partagent `ChromeDedie` ; l'onglet d'un rôle est marqué dans son
  `sessionStorage` comme pour Gemini. Chaque site n'ouvre sa fenêtre qu'au premier
  message. **Avertissement dans Paramètres** : ces sites interdisent l'usage
  automatisé dans leurs conditions ; le compte peut être limité ; les clés API
  sont la voie stable.

## 5. Rapidité et stabilité (étape 1)

- `Sonde` (`pilote/sonde.py`) : un `page.evaluate` renvoie d'un coup
  questions, réponses, génération en cours, bandeau de limite, texte et HTML de
  la dernière réponse ; gardé 50 ms, il sert toutes les vérifications d'un même
  tour de boucle. Intervalles : envoi 0,25 s, nouvelle réponse 0,2 s, fin 0,25 s.
- `POST /api/conversations/{id}/messages?flux=1` : réponse `application/x-ndjson`,
  lignes `{"type":"partiel","texte","html"}` (au plus toutes les 150 ms), puis
  `{"type":"message","message":{…}}` ou `{"type":"erreur","erreur":…}`.
  `POST /api/conversations/{id}/arreter` coupe la réponse en cours.
- Fils du serveur : la limite d'anyio passe à 200 au démarrage de chaque app.
- SQLite : `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`.
- Flux Cowork : reconnexion automatique (1 s, 2 s, 4 s… plafonné à 10 s) avec
  `depuis` = évènements déjà reçus.
- API réseau, `stream: true` : vrais morceaux au fil de l'eau (deltas).

## 6. Interface (étape 2) — maquette validée le 19/10

- **Barre latérale** : logo `agent.first` (point terre cuite), Nouvelle
  (Ctrl N), Rechercher (Ctrl K, palette), Tableau de bord ; conversations par
  date, avec renommer et supprimer au survol ; en bas, l'état de chaque
  fournisseur actif (point + nom + « limite 14:58 ») et Paramètres.
- **Fil** : réponse en texte sans carte ; blocs de code avec langue et bouton
  Copier ; curseur terre cuite pendant l'écriture ; pied : point du fournisseur,
  modèle, durée, « secours » le cas échéant, Copier ; bouton « revenir en bas »
  quand on lit plus haut (le fil ne saute plus en bas pendant la lecture).
- **Zone de saisie** : un seul menu de modèles rangé par fournisseur (état,
  limite, modèles bloqués grisés), interrupteur « Secours si limite ou panne »
  en bas du menu ; menu Réflexion seulement si le fournisseur a des niveaux ;
  Arrêter remplace Envoyer pendant une réponse.
- **Notifications** discrètes (en bas au centre, 3 s) à la place de la pastille.
- **Paramètres** en onglets : Général (modèle par défaut, secours), Fournisseurs
  (sites : état et « Ouvrir pour se connecter » ; API : clé masquée, modèles
  affichés, « Tester »), API réseau, État.
- **Palette Ctrl K** : chercher une conversation, Nouvelle conversation,
  Paramètres, Tableau de bord.

## 7. Laissé au constructeur

Noms internes, découpage des modules JavaScript (`app.js` est déjà long : le fil,
Cowork, Paramètres et la palette vont dans leurs propres fichiers), textes exacts
des messages d'erreur (en français, disant quoi faire).
