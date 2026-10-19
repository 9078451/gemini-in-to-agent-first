# gemini-in-to-agent-first

**agent.first** : discuter avec Gemini (le site web, avec ton compte Google)
— et désormais avec d'autres IA — depuis une app sur mesure. L'app envoie
chaque message à **Agent First**, qui pilote un Chrome dédié sur
gemini.google.com (ou ChatGPT, Claude.ai), ou appelle une API par clé (Claude,
OpenAI, Mistral, Ollama…), lit la réponse **pendant qu'elle s'écrit** et la
garde dans l'historique.

## Installation (une fois)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Après une mise à jour, relance la seconde ligne : de nouvelles bibliothèques
sont nécessaires (`anthropic`, `markdown-it-py`).

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

- Sous la zone de saisie : **un seul menu des modèles**, rangé par fournisseur
  (avec son état : prêt, limite jusqu'à telle heure, déconnecté…), et le
  **niveau de réflexion** quand le fournisseur en a. Entrée envoie,
  Maj+Entrée va à la ligne.
- La réponse s'affiche **pendant qu'elle s'écrit** ; **Arrêter** (ou Échap) la
  coupe et garde ce qui est écrit. Blocs de code avec bouton Copier.
- **Ctrl+K** : chercher une conversation (titres et messages) ou une action ;
  **Ctrl+Maj+O** : nouvelle conversation. Renommer : crayon dans la barre, ou
  double-clic sur le titre.
- **Tableau de bord** : statistiques, recherche, reprise ou retrait d'une
  conversation (elle reste chez le fournisseur).
- **Paramètres** (onglets) : choix par défaut et secours, fournisseurs et clés,
  API réseau, état de Chrome, de Google et des fournisseurs.

L'historique est dans `donnees/historique.db` (sur ton PC, exclu de git).

## Fournisseurs d'IA

Active-les dans **Paramètres → Fournisseurs**.

- **Sites, avec ton compte**, pilotés dans le Chrome dédié comme Gemini :
  **ChatGPT** et **Claude.ai**. Clique « Ouvrir dans le Chrome dédié » une fois
  pour t'y connecter. ⚠️ Ces sites interdisent l'usage automatisé dans leurs
  conditions : ton compte peut être limité. Leurs pages changent souvent ; si
  un repère n'est plus trouvé : `python -m pilote.inspecter --site chatgpt`
  (ou `claude_web`), puis corrige `pilote/sites.py`.
- **API, avec une clé** (plus rapides et stables) : Claude (Anthropic),
  OpenAI, Gemini API (clé gratuite sur AI Studio), Mistral, Groq, OpenRouter,
  DeepSeek, xAI, et **Ollama** sur ce PC (gratuit, sans Internet), ou tout
  serveur « compatible OpenAI » (LM Studio…). Colle la clé, puis « Lire la
  liste » pour choisir les modèles du menu. Les clés restent dans
  `donnees/fournisseurs.json` (exclu de git) et ne sont jamais réaffichées en
  entier.

Changer de fournisseur au milieu d'une conversation marche : le nouveau reçoit
l'historique.

**Secours si limite ou panne** (Paramètres → Général, ou l'interrupteur en bas
du menu des modèles) : si le fournisseur d'une conversation atteint sa limite
ou ne répond plus, le message repart chez le fournisseur de secours, avec
l'historique, et la conversation y continue. La réponse l'indique (« secours ·
Gemini à sa limite »). En Cowork, la tâche continue chez le secours.

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
abandonner une longue demande sans répondre. Cowork marche aussi avec les
autres fournisseurs (choisis-le dans le menu des modèles avant d'envoyer) : un
modèle par API (Claude, OpenAI…) y est souvent plus rapide et plus régulier.

**Pilote plus rapide.** Chaque vérification de la page (la réponse est-elle
finie ?) se fait en un seul échange avec Chrome : 2,6 ms au lieu de 25 ms,
mesuré sur la vraie page Gemini le 19/10.

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

`model` : un modèle de Gemini (« 4 Argon »), ou **« fournisseur/modèle »** pour
un autre fournisseur actif (`anthropic/claude-opus-5-5`, `ollama/llama3.2`,
`chatgpt/Par défaut`…) ; `/v1/models` les liste tous. Avec `stream=True`, la
réponse arrive **au fil de l'eau**, morceau par morceau. Le secours s'applique
aussi.

Renvoyer l'historique complet (comme le fait un client OpenAI) continue la même
conversation. Ces appels passent par la fenêtre du Chat : ils répondent
pendant une tâche Cowork, mais un à la fois par site (les API par clé, elles,
répondent à plusieurs demandes en même temps).

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
« api »), et une demande d'accord s'y signale aussi. Désactiver l'API :
`API_ACTIVE = False` dans `config.py`. **Quiconque a la clé peut faire agir
Cowork sur ton PC** : garde-la pour toi et régénère-la au moindre doute.

## Outils

```
.venv\Scripts\python -m pytest                                          tests Python
node --test tests/web/outils.test.mjs tests/web/outils_cowork.test.mjs  tests JavaScript
.venv\Scripts\python -m pilote.modes                                    modèles et niveaux de Gemini
.venv\Scripts\python -m pilote.essai "Bonjour"                          essai direct du pilote
.venv\Scripts\python -m pilote.inspecter                                repères de la page Gemini
.venv\Scripts\python -m pilote.inspecter --site chatgpt                 repères de ChatGPT (ou claude_web)
```

**Port du Chrome dédié** : Windows réserve parfois au démarrage une plage de
ports qui contient le 9222 (voir `netsh int ipv4 show excludedportrange
protocol=tcp`). Agent First le détecte : Chrome prend alors un port libre et
Agent First le retrouve tout seul.

Conception : `docs/superpowers/specs/` · Plans : `docs/superpowers/plans/`
