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
s'ouvre dans sa propre fenêtre. Fermer la console arrête Agent First.

- **Nouvelle conversation**, choix du **modèle** et du **niveau de réflexion**
  en haut de la discussion ; Entrée envoie, Maj+Entrée va à la ligne.
- **Accueil / Historique** : statistiques, recherche, reprise ou retrait d'une
  conversation (elle reste dans Gemini).
- **Paramètres** : modèle et niveau par défaut, état de Chrome et de Google.

L'historique est dans `donnees/historique.db` (sur ton PC, exclu de git).

## Outils

```
.venv\Scripts\python -m pytest                 tests Python
node --test tests/web/outils.test.mjs          tests JavaScript
.venv\Scripts\python -m pilote.modes           modèles et niveaux de Gemini
.venv\Scripts\python -m pilote.essai "Bonjour" essai direct du pilote
.venv\Scripts\python -m pilote.inspecter       repères de la page Gemini
```

Conception : `docs/superpowers/specs/` · Plans : `docs/superpowers/plans/`
