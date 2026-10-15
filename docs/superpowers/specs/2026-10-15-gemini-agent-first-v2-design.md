# agent.first v2 — app web, modèles, historique — fiche de conception

Date : 2026-10-15
Statut : à valider
Remplace l'interface de la v1 (`docs/superpowers/specs/2026-10-15-gemini-agent-first-design.md`) ;
le pilote navigateur et la file d'attente de la v1 sont gardés.

## 1. But

Une app **en HTML**, servie par Agent First et ouverte dans une fenêtre
d'application Chrome, dans le style des maquettes validées (sombre, épuré,
barre latérale, cartes arrondies, accent vert). On peut y :

- discuter avec Gemini (site web, compte Google de l'utilisateur) ;
- **choisir le modèle et le niveau de réflexion** avant chaque message ;
- **retrouver toutes ses conversations** et en reprendre une ancienne ;
- consulter un **historique** avec recherche et statistiques.

**C'est réussi quand :**

1. Double-clic sur `demarrer.bat` → une fenêtre « agent.first » s'ouvre (sans
   onglets ni barre d'adresse) sur la page d'accueil.
2. Choisir « 3.1 Pro » + « Max. », écrire un message → la réponse arrive
   **avec sa mise en forme** (titres, listes, code), et Gemini a bien utilisé
   ce modèle et ce niveau.
3. La conversation apparaît dans la barre latérale ; après avoir fermé puis
   rouvert l'app, un clic dessus réaffiche tous ses messages, et un nouveau
   message continue la même conversation Gemini.
4. La page Accueil / Historique affiche les statistiques et la liste des
   conversations ; la recherche retrouve une conversation par un mot de ses
   messages.
5. En cas de problème (Agent First arrêté, pas connecté à Google, modèle
   introuvable, délai dépassé), un message clair s'affiche dans l'app.

## 2. Ce que tu as dit / ce que j'ai supposé

| Point | Source |
|---|---|
| App construite en HTML, comme un site web | toi |
| Style des maquettes (sombre, menu, cartes, accent vert) | toi (validé) |
| Choix du modèle et du niveau de réflexion | toi |
| Liste des conversations, reprise des anciennes | toi |
| Système d'historique pour l'app | toi |
| Page servie par Agent First, fenêtre d'app Chrome (solution 1) | toi (validé) |
| Historique stocké sur le PC (SQLite), messages compris | hypothèse |
| Réponses affichées avec leur mise en forme | hypothèse |
| Les anciennes conversations Gemini (faites hors de l'app) ne sont pas importées | hypothèse |
| La fenêtre CustomTkinter de la v1 est supprimée | hypothèse |

## 3. Modèles et niveaux (relevés sur ton Gemini le 2026-10-15)

| Modèle | Description Gemini |
|---|---|
| 3.5 Flash-Lite | Réponses les plus rapides |
| 3.8 Flash | Aide polyvalente |
| 3.1 Pro | Raisonnement avancé |
| 4 Argon | Tâches complexes |

Niveaux de réflexion (sous-menu « Niveau de réflexion ») : **Min.** (rapide et
efficace), **Moyen** (équilibré), **Max.** (très poussé).

- La liste n'est pas écrite en dur dans l'app : Agent First la **lit dans le
  sélecteur de Gemini** à la première demande puis la garde en mémoire ; si
  Chrome n'est pas prêt, il renvoie la liste ci-dessus (valeurs par défaut
  dans `config.py`).
- Si Gemini ne propose pas le sous-menu « Niveau de réflexion » pour un modèle,
  le choix de niveau est grisé dans l'app pour ce modèle.

## 4. Architecture

```
┌──────────────────────────────┐  HTTP local   ┌──────────────────────────────┐
│ Fenêtre d'app Chrome         │ ────────────▶ │ Agent First (FastAPI)        │
│ (ton Chrome habituel,        │ ◀──────────── │ 127.0.0.1:8765               │
│  mode --app)                 │   JSON        │  · sert la page web          │
│ index.html + app.css + app.js│               │  · API /api/...              │
└──────────────────────────────┘               │  · historique (SQLite)       │
                                               │  · file d'attente (v1)       │
                                               └──────────────┬───────────────┘
                                                              │ un message à la fois
                                               ┌──────────────▼───────────────┐
                                               │ Pilote navigateur (v1 +)     │
                                               │  · choisit modèle et niveau  │
                                               │  · tape, attend, lit (HTML)  │
                                               └──────────────┬───────────────┘
                                                              │ port 9222
                                               ┌──────────────▼───────────────┐
                                               │ Chrome dédié — Gemini        │
                                               └──────────────────────────────┘
```

Deux Chrome distincts : la **fenêtre d'app** (ton Chrome habituel, affiche
l'interface) et le **Chrome dédié** (profil séparé, piloté, connecté à
Gemini). Le pilote ne touche jamais la fenêtre d'app.

### 4.1 Pilote navigateur (`pilote/`) — ajouts à la v1

- `envoyer(adresse, texte, modele=None, niveau=None)` :
  1. ouvre la conversation (comme en v1) ;
  2. si `modele`/`niveau` diffèrent de ce que le pilote a réglé en dernier
     (ou au premier message après démarrage) : ouvre le sélecteur de mode,
     clique le modèle (repéré par son nom, ex. « 3.1 Pro »), puis rouvre le
     sélecteur → « Niveau de réflexion » → clique le niveau ; vérifie que le
     bouton du sélecteur affiche le modèle choisi, sinon erreur
     `ModeleIntrouvable` ;
  3. tape, envoie, attend la fin (inchangé) ;
  4. lit la réponse en **texte** (comme en v1) **et en HTML** : copie du bloc
     réponse, sans les boutons, icônes et décorations de Gemini (repères dans
     `selecteurs.py`).
- `ResultatGemini` gagne : `html`, `modele`, `niveau`, `duree` (secondes).
- `lister_modeles()` : ouvre le sélecteur, lit les modèles et les niveaux
  (et pour quels modèles le niveau existe), referme avec Échap sans rien
  changer.
- Nouveaux repères dans `selecteurs.py` : bouton du sélecteur de mode, options
  de modèle, entrée « Niveau de réflexion », options de niveau, éléments à
  retirer du HTML de la réponse.

### 4.2 Historique (`agent_first/historique.py`)

Base SQLite `donnees/historique.db` (remplace `donnees/conversations.json`,
qui n'est pas repris : il ne contenait aucun message).

- `conversations` : id, titre (début du 1er message, 60 caractères max., sur
  une ligne), adresse Gemini, modèle et niveau du dernier message, créée le,
  modifiée le.
- `messages` : id, conversation, rôle (`toi` / `gemini` / `erreur`), texte,
  HTML (réponses Gemini seulement, **nettoyé** : seules les balises de mise
  en forme sont gardées), modèle, niveau, durée, date.
- Fonctions : créer / lister (recherche dans titres et messages, filtre de
  période 7 j / 30 j / tout) / lire une conversation avec ses messages /
  ajouter un message / enregistrer l'adresse Gemini / supprimer une
  conversation (de l'historique de l'app seulement, pas de Gemini) /
  statistiques.
- Statistiques sur la période : nombre de conversations, nombre de messages,
  modèle le plus utilisé, temps de réponse moyen.

### 4.3 API d'Agent First (`agent_first/serveur.py`)

| Route | Rôle |
|---|---|
| `GET /` et `/static/...` | la page web |
| `GET /api/etat` | Agent First, Chrome dédié, compte Google |
| `GET /api/modeles` | modèles et niveaux disponibles |
| `GET /api/conversations?recherche=&periode=` | liste pour la barre latérale et l'historique |
| `POST /api/conversations` | nouvelle conversation (titre vide) |
| `GET /api/conversations/{id}` | conversation et tous ses messages |
| `DELETE /api/conversations/{id}` | retire de l'historique de l'app |
| `POST /api/conversations/{id}/messages` `{texte, modele, niveau}` | envoie à Gemini, enregistre question et réponse, renvoie la réponse |
| `GET /api/statistiques?periode=` | cartes de la page Accueil |

Le message de l'utilisateur est enregistré **avant** l'envoi ; en cas d'erreur,
un message `erreur` est enregistré aussi (l'historique garde la trace). Les
erreurs renvoient `{"erreur": "..."}` comme en v1.

### 4.4 L'app web (`agent_first/web/`)

`index.html`, `app.css`, `app.js` — HTML/CSS/JavaScript simples, sans outil
de compilation ni dépendance téléchargée depuis Internet (icônes en SVG
intégré, police système Segoe UI). Une seule page, deux vues :

- **Barre latérale** (toujours visible, repliable) : logo `agent.first`,
  recherche (touche `/`), « Nouvelle conversation », « Accueil »,
  CONVERSATIONS groupées (Aujourd'hui, Hier, 7 derniers jours, Plus ancien),
  APP (Historique, Paramètres), état du compte Google en bas.
- **Vue Discussion** : titre de la conversation ; menu du modèle et
  sélecteur Min. / Moyen / Max. (une conversation rouverte reprend son
  dernier modèle et niveau ; une nouvelle prend ceux par défaut) ; messages (les tiens à droite, ceux de
  Gemini dans une carte avec modèle, niveau et durée, bouton Copier) ;
  barre de saisie en pilule (Entrée envoie, Maj+Entrée va à la ligne) ;
  pastille d'état (« Gemini prêt ● », « Gemini réfléchit… 12 s »).
- **Vue Accueil / Historique** : « Bon retour sur agent.first », recherche,
  4 cartes de statistiques, filtre 7 jours / 30 jours / Tout, liste des
  conversations (clic = reprendre, icône corbeille = retirer après
  confirmation).
- **Paramètres** (panneau) : modèle et niveau par défaut pour les nouvelles
  conversations (gardés dans le navigateur), état de Chrome et de Google.

Le HTML des réponses est nettoyé côté serveur avant d'être affiché.

### 4.5 Lancement

`demarrer.bat` lance `python -m agent_first --ouvrir` dans une console
réduite : Agent First démarre, puis ouvre la fenêtre d'app
(`chrome.exe --app=http://127.0.0.1:8765 --window-size=1280,820`) dès que le
serveur répond. Fermer la console arrête Agent First.

## 5. Erreurs (ajouts à la v1)

| Situation | Ce qui se passe |
|---|---|
| Modèle ou niveau introuvable dans Gemini | « Le modèle « X » n'est plus proposé par Gemini » + liste des modèles relue |
| Niveau non proposé pour ce modèle | message envoyé sans changer le niveau ; la réponse indique le niveau réel (« niveau : non applicable ») |
| Conversation supprimée de l'historique pendant un envoi | réponse renvoyée, mais pas enregistrée |
| Base `historique.db` illisible | mise de côté (`historique.corrompu.db`), nouvelle base vide, avertissement dans le journal |

Les cas de la v1 (Agent First arrêté, pas connecté, vérification Google,
délai dépassé, repère introuvable) restent valables.

## 6. Tests

- **Automatiques (pytest)** : historique (création, recherche, périodes,
  statistiques, suppression, base corrompue), nettoyage du HTML, routes de
  l'API avec un faux pilote, choix du modèle transmis au pilote.
- **Pilote réel** : `python -m pilote.essai "..." --modele "3.1 Pro" --niveau Max.`
  et `python -m pilote.modeles` (liste lue dans Gemini).
- **App** : vérifiée dans un vrai navigateur (captures), puis les 5 critères
  de la section 1 à la main.

## 7. Fichiers

```
agent_first/   serveur.py (API + page), historique.py, nettoyage.py,
               file_attente.py (v1), __main__.py (+ --ouvrir)
agent_first/web/  index.html, app.css, app.js
pilote/        gemini.py (+ modèle, niveau, HTML), selecteurs.py (+ repères),
               modeles.py (lecture du sélecteur), essai.py (+ options)
supprimés :    gui/ (fenêtre CustomTkinter), agent_first/conversations.py,
               tests correspondants, customtkinter dans requirements.txt
ajouté :       nh3 (nettoyage HTML) dans requirements.txt
```

## 8. Ordre de construction

1. **Pilote** : lecture des modèles, choix du modèle et du niveau, réponse en
   HTML (la partie risquée, vérifiée sur le vrai Gemini d'abord).
2. **Historique** SQLite + nettoyage HTML.
3. **API** d'Agent First (nouvelles routes, faux pilote dans les tests).
4. **App web** : barre latérale + vue Discussion.
5. **App web** : vue Accueil / Historique + Paramètres.
6. **Lancement** (`--ouvrir`, `demarrer.bat`), suppression de la v1 GUI,
   README.

## 9. Hors du périmètre

- Importer les conversations faites directement dans Gemini.
- Affichage de la réponse mot à mot pendant qu'elle s'écrit.
- Envoyer des fichiers ou images ; bouton « Interrompre ».
- Renommer une conversation ; supprimer une conversation **dans Gemini**.
- Utilisation depuis un autre appareil (tout reste sur 127.0.0.1).

## 10. À savoir

- Les points de la v1 restent vrais (conditions d'utilisation de Google,
  port 9222 local, profil Chrome dédié à ne pas partager).
- `donnees/historique.db` contient tous tes échanges avec Gemini : il reste
  sur ton PC et est exclu de git.
