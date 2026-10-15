# gemini-in-to-agent-first

Discuter avec Gemini (site web) depuis une fenêtre sur mesure : la fenêtre
envoie le message à **Agent First**, qui pilote un Chrome dédié connecté à
Google, lit la réponse et la renvoie.

## Installation (une fois)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Au premier lancement, une fenêtre Chrome séparée s'ouvre sur Gemini :
connecte-toi à ton compte Google dedans (une seule fois).

## Utilisation

Double-clique `demarrer.bat`.

## Tests

```
.venv\Scripts\python -m pytest
```

Conception : `docs/superpowers/specs/` · Plan : `docs/superpowers/plans/`
