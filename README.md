# gemini-in-to-agent-first

**agent.first** : discuter avec Gemini (le site web, avec ton compte Google)
depuis une app sur mesure. L'app envoie chaque message à **Agent First**, qui
pilote un Chrome dédié sur gemini.google.com, choisit le modèle et le niveau
de réflexion, lit la réponse et la garde dans l'historique.

## Installation (une fois)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Au premier lancement, une fenêtre Chrome séparée (le « Chrome dédié ») s'ouvre
sur Gemini : connecte-toi à ton compte Google dedans, une seule fois.

## Utilisation

Double-clique `demarrer.bat` : Agent First démarre (console réduite) et l'app
s'ouvre dans sa propre fenêtre. Le Chrome dédié s'ouvre aussitôt sur Gemini, en
arrière-plan, pour que le premier message n'attende pas. Fermer la console
arrête Agent First.

Le Chrome dédié a **deux fenêtres Gemini** : l'une pour les tâches Cowork,
l'autre pour le Chat et l'API réseau. Le Chat répond donc pendant qu'une tâche
Cowork tourne. Laisse-les ouvertes (cachées derrière d'autres, elles continuent
d'écrire) ; une fenêtre fermée est rouverte au message suivant. Si le Chrome
dédié était déjà ouvert avant la mise à jour, ferme-le une fois : Agent First le
relance avec les bons réglages.

- **Nouvelle conversation**, choix du **modèle** et du **niveau de réflexion**
  sous la zone de saisie ; Entrée envoie, Maj+Entrée va à la ligne.
- **Créer** (sous la zone de saisie) : Texte, **Image**, **Vidéo** ou **Musique**
  (voir plus bas). Une erreur propose **Réessayer** ; chaque bloc de code a son
  bouton Copier.
- **Joindre des fichiers** (photos, PDF, sons, vidéos…, 10 au plus, 50 Mo chacun) :
  trombone, Ctrl+V d'une capture d'écran, ou glisser-déposer sur la discussion.
  Avec **Créer → Image**, une photo jointe est retouchée (« mets le ciel en
  violet »).
- La réponse **s'écrit en direct** ; **Arrêter** l'interrompt dans Gemini et garde
  ce qu'il avait déjà écrit (marqué « arrêtée »).
- **Exporter** (en-tête de la discussion) : un `.zip` avec la conversation en
  Markdown et tous ses médias. Le **tableau de bord** montre les derniers médias
  créés (filtres Images, Vidéos, Sons).
- **Accueil / Historique** : statistiques, recherche, reprise ou retrait d'une
  conversation (elle reste dans Gemini).
- **Paramètres** : modèle et niveau par défaut, état de Chrome et de Google,
  adresse et clé de l'API réseau.

L'historique est dans `donnees/historique.db` (sur ton PC, exclu de git).

## Images, vidéos et musique

Choisis **Créer → Image, Vidéo ou Musique**, puis décris ce que tu veux. Agent
First coche l'outil de création de Gemini (menu « Outils » de la page, s'il le
trouve), rédige la demande pour que Gemini crée vraiment le média (et ne se
contente pas de le décrire), attend qu'il soit prêt, puis le télécharge avec ta
session Google (en taille réelle pour une image, si possible).

- Les médias s'affichent dans la discussion : une image s'agrandit d'un clic,
  vidéos et sons ont leur lecteur, chacun a un bouton **Télécharger**.
- Ils sont gardés dans `donnees/medias/<conversation>/` et reviennent quand tu
  rouvres la conversation ; la retirer de l'historique retire ses médias.
- Délais (`DELAI_MEDIA` dans `config.py`) : 4 min pour une image, 15 min pour une
  vidéo, 10 min pour de la musique. Une vidéo Veo prend souvent plusieurs
  minutes ; le Chat attend pendant ce temps (Cowork, lui, continue).
- Si Gemini répond sans média (refus, outil indisponible avec ce modèle ou ce
  compte), un avertissement le dit : reformule, ou change de modèle.
- Dans une conversation qui a déjà un média, une nouvelle demande peut le
  modifier (« même image, mais en hiver »).

Si Google change sa page et qu'un média n'est plus repéré :
`python -m pilote.inspecter --medias` montre ce qu'Agent First voit dans la
dernière réponse ; les repères sont dans `pilote/selecteurs.py`.

## Mode Cowork

En **Cowork**, Gemini travaille dans un dossier de ton PC, comme Claude Code :
il fait un **plan**, lit, crée et modifie des fichiers, lance des commandes et
des serveurs, les **vérifie** (il visite lui-même `http://localhost:…`), puis
finit. Agent First exécute ses actions et le tient dans son rôle :

- chaque demande part avec le cadre complet (rôle, actions, contenu du dossier,
  processus lancés, dernière tâche) ;
- « fini » est refusé tant que le plan a des étapes non cochées, ou si du code a
  été écrit sans être vérifié ;
- à la fin, un **bilan factuel** (fichiers créés, modifiés, supprimés,
  commandes et leur code de sortie) est calculé par Agent First, pas par Gemini ;
- suppressions et commandes risquées attendent ton accord ; les fichiers hors
  du dossier de travail sont refusés.

Actions de Gemini (en anglais) : `list read search create edit delete run start
logs stop visit plan ask done`. Les serveurs lancés avec `start` restent actifs
après la tâche (pastille dans l'en-tête, bouton Arrêter) et s'arrêtent avec
Agent First.

**Rapidité.** Le temps part surtout chez Gemini, à chaque aller-retour :

- Gemini enchaîne tout ce qu'il peut dans un seul message (créer, lancer,
  vérifier, finir) ; le lot s'arrête à la première erreur ;
- le fil montre le temps de chaque réponse (« Gemini a répondu en 14 s ») et le
  bilan le total, pour choisir le modèle le plus rapide pour toi ;
- au-delà de 30 messages (`TOURS_GEMINI_MAX` dans `config.py`), la demande
  suivante part dans une conversation Gemini neuve, avec un résumé des demandes
  précédentes : une longue conversation ralentit Gemini et le fait dériver ;
- `search` ne fouille pas `node_modules`, `.venv`, `.git` ni les fichiers
  binaires ; `read` peut lire un passage (`start`, `end`) d'un gros fichier.

Conseil : 4 Argon avec la réflexion **Min.** ou **Moyen** ; « Max. » peut
abandonner une longue demande sans répondre.

## API réseau

Agent First ouvre aussi une API sur le port **8766** pour d'autres programmes,
sur ce PC ou les autres appareils de ton réseau. Adresse et clé : **Paramètres**
de l'app (la clé est aussi dans `donnees/cle_api.txt`). Chaque appel exige
l'en-tête `Authorization: Bearer <clé>`. Documentation interactive :
`http://<adresse>:8766/docs`. Au premier lancement, Windows demande d'autoriser
Python dans le pare-feu : accepte « réseaux privés » seulement.

**Format OpenAI** — n'importe quel client OpenAI fonctionne :

```python
from openai import OpenAI

client = OpenAI(base_url="http://192.168.1.10:8766/v1", api_key="<clé>")
reponse = client.chat.completions.create(
    model="4 Argon",                      # un nom de /v1/models, ou "agent-first"
    reasoning_effort="low",               # low / medium / high → Min. / Moyen / Max.
    messages=[{"role": "user", "content": "Bonjour"}],
)
print(reponse.choices[0].message.content)
```

Renvoyer l'historique complet (comme le fait un client OpenAI) continue la même
conversation Gemini. Ces appels passent par la fenêtre du Chat : ils répondent
pendant une tâche Cowork, mais un à la fois (les suivants attendent leur tour).

- `model` : un nom de `/v1/models`, ou à la façon des clients (« gemini-3.1-pro »,
  « 3.1-pro-preview », « argon ») ; un nom inconnu (« gpt-4o ») ou
  « agent-first » garde le modèle déjà choisi dans Gemini.
- `reasoning_effort` : `none`/`minimal`/`low` → Min., `medium` → Moyen,
  `high`/`xhigh` → Max.
- `stream: true` : un commentaire `: ping` part toutes les 10 s de silence (les
  clients n'abandonnent plus pendant que Gemini réfléchit) ; une erreur arrive
  au format OpenAI (`data: {"error": …}`).
- Une demande qui n'a pas pu commencer à temps est retirée de la file : elle ne
  part pas vers Gemini plus tard. Une réponse arrivée après le délai est quand
  même gardée dans l'historique.
- **Fichiers joints** : les morceaux `image_url` (adresse `data:` ou `http(s)`),
  `input_image`, `file` / `input_file` (`file_data`, `file_url`) et `input_audio`
  sont envoyés à Gemini avec le message (10 au plus, 50 Mo chacun).
- `stream: true` envoie le texte **au fil de l'écriture** de Gemini, morceau par
  morceau ; les médias arrivent dans le dernier morceau.

**Images** (format OpenAI) :

```python
reponse = client.images.generate(prompt="un renard roux dans la neige", size="1792x1024")
print(reponse.data[0].url)          # lien signé : s'ouvre sans la clé (navigateur, <img>)
# response_format="b64_json" donne l'image elle-même ; n=2 demande deux versions

retouche = client.images.edit(image=open("photo.jpg", "rb"), prompt="mets le ciel en violet")
# Gemini ne prend pas de masque : décris la zone à changer dans le prompt
```

Dans `/v1/chat/completions`, `"modalities": ["image", "text"]` (comme OpenRouter)
ou `"media": "image" | "video" | "music"` fait créer le média : la réponse le
donne dans `message.media` (liens signés), `message.images` (images en
`data:`, format OpenRouter) et sous forme de liens dans le texte.

**Vidéos et musique** :

```
curl -H "Authorization: Bearer <clé>" -H "Content-Type: application/json" ^
     -d "{\"type\": \"video\", \"prompt\": \"une vague au ralenti\", \"wait\": false}" ^
     http://192.168.1.10:8766/v1/media/generations
```

| Route | Rôle |
|---|---|
| `POST /v1/images/generations` `{prompt, n?, size?, response_format?, model?}` | image(s), format OpenAI |
| `POST /v1/images/edits` (multipart `image`/`image[]`, `prompt`… ou JSON `{images, prompt}`) | retouche de photo(s), format OpenAI |
| `POST /v1/media/generations` `{type, prompt, images?, n?, size?, response_format?, model?, wait?}` | image, vidéo ou musique, à partir d'images si `images` ; `wait: false` → 202 tout de suite |
| `GET /v1/media/generations/{id}` | état (`in_progress`, `completed`, `failed`) et médias |
| `GET /v1/media/{conversation}/{fichier}` | le fichier (`?sig=` d'un lien signé, ou la clé ; `?download=true`) |
| `GET /v1/conversations/{id}` | une conversation de l'historique et ses médias |
| `GET /health` | Agent First répond (sans clé) |

Un lien signé ne donne accès qu'à son média ; régénérer la clé les invalide tous.
L'API accepte les appels de pages web d'autres appareils (CORS) : la clé reste
exigée.

**Tâches Cowork** :

```
curl -H "Authorization: Bearer <clé>" -H "Content-Type: application/json" ^
     -d "{\"folder\": \"C:\\\\projets\\\\site\", \"request\": \"Ajoute une page contact\"}" ^
     http://192.168.1.10:8766/v1/cowork
```

| Route | Rôle |
|---|---|
| `POST /v1/cowork` `{folder, request, model?, reasoning_effort?}` | lance une tâche → `{id, status}` |
| `GET /v1/cowork/{id}/events` | étapes en direct (SSE) |
| `GET /v1/cowork/{id}` | état, plan, résumé, bilan |
| `POST /v1/cowork/{id}/decision` `{step, approve, always?}` | accord sur une action risquée |
| `POST /v1/cowork/{id}/messages` `{text}` | nouvelle demande, ou réponse à une question |
| `POST /v1/cowork/{id}/stop` | arrête la tâche |

Sans `reasoning_effort`, une tâche Cowork utilise le niveau par défaut de l'app
(Min.) : avec « Max. », Gemini peut abandonner une longue demande sans répondre.

Les conversations de l'API apparaissent dans l'historique de l'app (marquées
« api »), médias compris, et une demande d'accord s'y signale aussi. Désactiver l'API :
`API_ACTIVE = False` dans `config.py`. **Quiconque a la clé peut faire agir
Cowork sur ton PC** : garde-la pour toi et régénère-la au moindre doute.

## Outils

```
.venv\Scripts\python -m pytest                                          tests Python
node --test tests/web/outils.test.mjs tests/web/outils_cowork.test.mjs  tests JavaScript
.venv\Scripts\python -m pilote.modes                                    modèles et niveaux de Gemini
.venv\Scripts\python -m pilote.essai "Bonjour"                          essai direct du pilote
.venv\Scripts\python -m pilote.essai "Un chat roux" --outil image       essai d'une création (médias dans journaux\)
.venv\Scripts\python -m pilote.essai "Décris" --joindre photo.jpg        essai d'une pièce jointe
.venv\Scripts\python -m pilote.inspecter                                repères de la page Gemini
.venv\Scripts\python -m pilote.inspecter --medias                       médias de la dernière réponse
```

`tests/test_pilote_page.py` lance le pilote face à une fausse page Gemini, dans
le Chrome de `CHEMIN_CHROME` (sans fenêtre) : médias, fichiers joints, réponse en
direct puis arrêtée. Il est passé si aucun Chrome ne démarre.

Conception : `docs/superpowers/specs/` · Plans : `docs/superpowers/plans/`
