# agent.first — le Chat répond pendant une tâche Cowork — fiche de conception

Date : 2026-10-17
Statut : à valider
S'ajoute à la fiche v3 (`2026-10-16-agent-first-v3-design.md`).

## 1. Pourquoi

Tout passe par une seule file (`agent_first/file_attente.py`) : un fil, un
pilote Playwright, un onglet Gemini. Une tâche Cowork occupe cette file du début
à la fin (souvent plusieurs minutes). Pendant ce temps :

- un message du Chat de l'app attend son tour, puis échoue (504 après 290 s) ;
- `/v1/chat/completions` fait de même ;
- `/v1/models`, `/api/modeles` et `/api/etat` renvoient des valeurs par défaut.

## 2. But et critères de réussite

Le Chat (app et API réseau) répond pendant qu'une tâche Cowork tourne, avec un
second onglet Gemini dans le même Chrome dédié.

**C'est réussi quand :**

1. Une tâche Cowork tourne ; un message du Chat de l'app reçoit sa réponse sans
   attendre la fin de la tâche.
2. Pareil pour `POST /v1/chat/completions`.
3. `/v1/models` lit la vraie liste dans Gemini pendant une tâche Cowork.
4. La tâche Cowork continue avec **son** modèle et **son** niveau, même si le
   Chat en a choisi d'autres entre-temps.
5. Deux tâches Cowork restent l'une après l'autre ; deux messages du Chat aussi.

## 3. Essai réel (17/10, compte de l'utilisateur)

Deux connexions Playwright (une par fil) au même Chrome (CDP 9222), un onglet
chacune, deux messages envoyés au même instant.

| Essai | Onglet A | Onglet B | Résultat |
|---|---|---|---|
| même fenêtre | 4 Argon | 3.8 Flash | l'onglet de derrière bute (menu, texte) : à éviter |
| fenêtres séparées | 3.8 Flash | 3.8 Flash | les deux s'écrivent en même temps, justes (13 s et 10 s) |
| fenêtres séparées | 4 Argon | 3.8 Flash | 2 essais : B juste les deux fois ; A juste une fois (20 s), abandonné une fois (210 s) |
| fenêtres séparées | 4 Argon | 4 Argon | 2 essais : les deux justes une fois (19 s et 29 s), les deux abandonnés une fois (210 s) |
| seul | 4 Argon | — | 3 essais : juste deux fois (55 s, 22 s), abandonné une fois (216 s) |

**Verdict : le compte accepte deux réponses en même temps.** L'abandon après
~210 s vient de 4 Argon, seul ou non (déjà connu, message `MessageAbandonne`).

Deux constats de plus :

- **Les réglages sont ceux du compte** : le modèle choisi dans un onglet devient
  celui de toute nouvelle discussion, dans l'autre onglet aussi.
- **Juste après le chargement d'une nouvelle discussion**, un clic sur le
  sélecteur de mode est ignoré (menu fermé, échec après 5 s). Le pilote actuel
  y est déjà exposé quand il change de modèle en ouvrant une discussion.

## 4. Schéma

```
                        Chrome dédié (un processus, port 9222, ton profil)
   ┌──── fenêtre 1 ─────────────────────┐        ┌──── fenêtre 2 ─────────────────┐
   │ onglet Gemini « cowork »           │        │ onglet Gemini « chat »         │
   │ (celle ouverte au lancement)       │        │ (ouverte par Agent First)      │
   └────────────────▲───────────────────┘        └────────────────▲───────────────┘
                    │ connexion CDP n° 1                          │ connexion CDP n° 2
        fil « file-gemini-cowork »                   fil « file-gemini-chat »
        PiloteGemini ──┐                       ┌──── PiloteGemini
                       └── ReglagesCompte ─────┘   (qui a changé le modèle/niveau en dernier)
        FileAttente cowork                            FileAttente chat
                    ▲                                             ▲
        ServiceCowork                                 serveur.py : Chat de l'app, /api/etat
        (app : /api/cowork/…,                         api_reseau.py : /v1/chat/completions
         API : /v1/cowork/…)                          CacheModes : /api/modeles, /v1/models
```

## 5. Ce qui change

| Où | Quoi |
|---|---|
| `pilote/chrome.py` | `ChromeDedie` reste partagé (lancer, `est_lance`) ; un verrou évite deux lancements. Nouveau `OngletGemini(chrome, role)` : la connexion Playwright d'**un** fil et **son** onglet. L'onglet est marqué (`sessionStorage`, clé `agent-first-onglet`) : retrouvé après un redémarrage d'Agent First, jamais pris par l'autre fil. « cowork » prend l'onglet Gemini non marqué (ou en ouvre un) ; « chat » ouvre sa propre fenêtre. |
| `pilote/chrome.py` | Chrome lancé avec `--disable-backgrounding-occluded-windows`, `--disable-renderer-backgrounding`, `--disable-background-timer-throttling` : une fenêtre cachée derrière d'autres continue d'écrire. |
| `pilote/gemini.py` | `ReglagesCompte` partagé par les deux pilotes : chaque changement de modèle/niveau y est noté ; un pilote dont l'autre a changé les réglages depuis sa dernière lecture relit le sélecteur avant d'envoyer (sinon la tâche Cowork pourrait partir sur le modèle du Chat). |
| `pilote/modes.py` | `_ouvrir` reclique si le menu ne s'est pas ouvert (jusqu'à 10 s). |
| `agent_first/file_attente.py` | `FileAttente(fabrique, nom=…)` : le nom du fil ; deux files coexistent. |
| `agent_first/cache_modes.py` | Reçoit la file du Chat : la liste se lit pendant une tâche Cowork. |
| `agent_first/cowork_service.py` | Reçoit la file Cowork ; commentaires à jour (un accord en attente ne bloque plus le Chat). |
| `agent_first/serveur.py`, `api_reseau.py` | Reçoivent la file du Chat (`file_chat`). |
| `agent_first/__main__.py` | Deux pilotes, deux files, deux préchauffages ; arrêt des deux. |
| `pilote/essai.py`, `modes.py`, `inspecter.py` | Passent par `chrome.onglet("cowork")`. |

Ce qui ne change pas : l'historique, le protocole Cowork, l'app web, l'API
(routes et formats).

## 6. Tests (faux pilotes)

- `FileAttente` : deux files tournent en même temps ; nom du fil.
- `ChromeDedie` : drapeaux de lancement ; deux fils qui lancent → un seul Chrome.
- Choix de l'onglet (fonction pure) : marqué, non marqué, onglet de l'autre jamais pris.
- `ReglagesCompte` : relire seulement si l'autre pilote a changé les réglages.
- Serveur et API : une tâche Cowork bloquée dans sa file n'empêche pas une
  réponse du Chat ni `/v1/models`.
- Essai réel : tâche Cowork lancée, message du Chat pendant qu'elle tourne.
