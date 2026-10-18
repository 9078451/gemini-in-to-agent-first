# agent.first — fichiers joints, réponse en direct, arrêt — fiche de conception

Date : 2026-10-18
Statut : réalisé ; repères de la zone de saisie à confirmer en essai réel (voir 5)
S'ajoute à la fiche « images, vidéos et musique » (2026-10-17).

## 1. Pourquoi

- Impossible de donner un fichier à Gemini : ni photo à retoucher, ni PDF à
  résumer, ni son à transcrire. L'API ne faisait que signaler la pièce jointe.
- La réponse n'apparaissait qu'une fois finie (parfois après plusieurs minutes),
  et rien ne permettait de l'arrêter.
- Les médias créés étaient dispersés dans les conversations, sans moyen de les
  retrouver ou d'emporter une conversation entière.

## 2. Critères de réussite

1. App : joindre (trombone, Ctrl+V, glisser-déposer), voir les fichiers dans la
   question, les retrouver en rouvrant la conversation.
2. API : `image_url`, `input_image`, `file`, `input_file`, `input_audio` partent
   avec le message ; `/v1/images/edits` retouche une photo (client OpenAI tel
   quel) ; `/v1/media/generations` accepte des images de départ.
3. La réponse s'écrit en direct dans l'app (NDJSON) et dans l'API (`stream`,
   morceau par morceau).
4. **Arrêter** clique « Interrompre » dans Gemini ; le début est gardé, marqué
   « arrêtée ». Un message qui attend son tour est retiré de la file.
5. Galerie des médias au tableau de bord ; export `.zip` (Markdown + médias).

## 3. Joindre un fichier dans Gemini (`pilote/pieces.py`)

Pour chaque fichier, trois façons, dans l'ordre :

1. le **coller** : évènement `paste` avec un `DataTransfer` sur l'éditeur ;
2. le **déposer** : `dragenter`, `dragover`, `drop` ;
3. le **bouton « + »** : sélecteur de fichiers intercepté par Playwright
   (`expect_file_chooser`), tout de suite ou par l'entrée « Importer des
   fichiers » de son menu. Aucune fenêtre de Windows ne s'ouvre.

Un fichier compte comme joint quand un aperçu de plus apparaît dans la zone de
saisie (hors du texte tapé, un par fichier) ; on ne passe à la façon suivante
que s'il n'est pas apparu, ce qui évite de le joindre deux fois. La façon qui a
marché passe en tête pour les fichiers suivants. Le message part une fois les
envois à Google finis (`TELEVERSEMENT_EN_COURS`). Si aucune façon ne marche :
`PieceRefusee`, et rien n'est envoyé.

## 4. Direct et arrêt

- `attendre_fin_reponse(au_fil=…)` transmet le texte à chaque changement ;
  `doit_arreter()` lève `Interrompue` avec le texte déjà écrit.
- Le pilote clique « Interrompre la réponse » et rend `ResultatGemini(interrompue=True)`.
- App : `POST /api/conversations/{id}/messages?direct=true` répond en NDJSON
  (`texte`, puis `fin`, `erreur` ou `arrete`) ; `POST /api/conversations/{id}/arreter`.
- API : le texte part dès qu'il prolonge ce qui a déjà été envoyé ; si Gemini
  réécrit un passage (rare), la fin complète à partir du préfixe commun.

## 5. À confirmer en essai réel

Repères déduits (`pilote/selecteurs.py`) : `bouton_importer`, `PIECES_SAISIE`,
`TELEVERSEMENT_EN_COURS`, `ENTREE_IMPORTER`. Vérifier avec :

```
python -m pilote.essai "Que vois-tu ?" --joindre photo.jpg
python -m pilote.essai "Mets le ciel en violet" --outil image --joindre photo.jpg
python -m pilote.essai "Résume" --joindre rapport.pdf
```

Le reste (les trois façons, une seule pièce par fichier, refus net, direct,
arrêt avec clic sur « Interrompre ») est vérifié dans Chromium face à une fausse
page Gemini (`tests/test_pilote_page.py`).
