# agent.first — le Chat répond pendant une tâche Cowork — fiche de conception

Date : 2026-10-17
Statut : validé (17/10), réalisé
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

- **Une discussion neuve reprend le dernier choix du compte** : le modèle choisi
  dans un onglet devient celui de toute nouvelle discussion, dans l'autre onglet
  aussi. **Une page déjà ouverte garde les siens** (le libellé du sélecteur de
  l'autre onglet ne bouge pas). Vu une seconde fois pendant l'essai de l'app :
  l'API demandait 3.8 Flash, le pilote croyait l'avoir, la discussion neuve
  était restée en 4 Argon (113 s pour « 2 + 2 ») — corrigé, voir 5.
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
                       └── ReglagesCompte ─────┘   (ce qu'une discussion neuve affichera)
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
| `pilote/gemini.py` | `ReglagesCompte` partagé par les deux pilotes : le dernier modèle/niveau choisi (ou lu dans une discussion neuve), donc ce qu'une discussion neuve affichera. Chaque pilote suit les réglages de **sa** page : connus après un choix ; repris de `ReglagesCompte` à l'ouverture d'une discussion neuve ; relus (menu) s'ils sont inconnus — conversation rouverte, onglet rouvert, choix raté, ou choix de l'autre onglet en cours. Sans changement, le menu n'est pas relu à chaque discussion. |
| `pilote/modes.py` | `_ouvrir` reclique si le menu ne s'est pas ouvert (jusqu'à 10 s). |
| `agent_first/file_attente.py` | `FileAttente(fabrique, nom=…)` : le nom du fil ; deux files coexistent. |
| `agent_first/cache_modes.py` | Reçoit la file du Chat : la liste se lit pendant une tâche Cowork. |
| `agent_first/cowork_service.py` | Reçoit la file Cowork ; commentaires à jour (un accord en attente ne bloque plus le Chat). |
| `agent_first/serveur.py`, `api_reseau.py` | Reçoivent la file du Chat (`file_chat`). |
| `agent_first/assemblage.py` (nouveau) | `assembler(fabrique_pilote, …)` : deux files (`file-gemini-cowork`, `file-gemini-chat`), leurs préchauffages, le service Cowork, l'app et l'API ; `AgentFirst.arreter()` arrête tout. Sorti de `__main__` pour être testé avec de faux pilotes. |
| `agent_first/__main__.py` | Journaux, Chrome, un pilote par rôle (`OngletGemini` + `ReglagesCompte` partagé), serveurs. |
| `pilote/essai.py`, `modes.py`, `inspecter.py` | Passent par `OngletGemini(chrome, "cowork", principal=True)`. |

Ce qui ne change pas : l'historique, le protocole Cowork, l'app web, l'API
(routes et formats).

## 6. Tests (faux pilotes)

- `FileAttente` : deux files tournent en même temps ; nom du fil.
- `ChromeDedie` : drapeaux de lancement ; deux fils qui lancent → un seul Chrome.
- Choix de l'onglet (fonction pure) : marqué, non marqué, onglet de l'autre jamais pris.
- Réglages (faux Gemini : réglages du compte + ceux de chaque page) : page
  ouverte qui garde les siens, discussion neuve qui reprend le dernier choix,
  pas de relecture sans changement, conversation ou onglet rouverts, choix de
  l'autre onglet en cours, choix raté à mi-chemin.
- Menu des modèles recliqué ; erreur claire s'il ne s'ouvre jamais.
- Assemblage (`tests/test_assemblage.py`) : une tâche Cowork bloquée dans son
  onglet n'empêche ni le Chat de l'app, ni `/v1/chat/completions`, ni
  `/v1/models`, ni `/api/etat` ; chaque pilote naît dans le fil de sa file.
- Essai réel : app lancée, tâche Cowork + Chat de l'app + API en même temps.
