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

- **Nouvelle conversation**, choix du **modèle** et du **niveau de réflexion**
  en haut de la discussion ; Entrée envoie, Maj+Entrée va à la ligne.
- **Accueil / Historique** : statistiques, recherche, reprise ou retrait d'une
  conversation (elle reste dans Gemini).
- **Paramètres** : modèle et niveau par défaut, état de Chrome et de Google,
  adresse et clé de l'API réseau.

L'historique est dans `donnees/historique.db` (sur ton PC, exclu de git).

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
conversation Gemini.

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
```

Conception : `docs/superpowers/specs/` · Plans : `docs/superpowers/plans/`
