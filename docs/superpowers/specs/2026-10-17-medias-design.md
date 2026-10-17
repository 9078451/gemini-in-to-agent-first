# agent.first — images, vidéos et musique — fiche de conception

Date : 2026-10-17
Statut : réalisé ; repères de la page à confirmer en essai réel (voir 6)
S'ajoute à la fiche « le Chat répond pendant une tâche Cowork ».

## 1. Pourquoi

Gemini crée des images, des vidéos (Veo) et de la musique, mais Agent First ne
lisait que le texte de la réponse (`message-content`) et ne gardait que son HTML
nettoyé, sans balise `img`. Une réponse faite d'une seule image finissait même
en « délai dépassé » : l'attente exigeait du texte. Ni l'app ni l'API ne
pouvaient donc créer ou récupérer un média.

## 2. But et critères de réussite

1. Depuis l'app : **Créer → Image / Vidéo / Musique**, le média s'affiche,
   s'agrandit (image), se lit (vidéo, son), se télécharge, et revient quand on
   rouvre la conversation.
2. Depuis l'API : `POST /v1/images/generations` au format OpenAI ;
   `POST /v1/media/generations` pour les trois types, avec suivi
   (`wait: false` puis `GET /v1/media/generations/{id}`) ; médias aussi dans
   `/v1/chat/completions` (`modalities` d'OpenRouter, ou `media`).
3. Un média se récupère par un lien signé (sans la clé, pour ce média seul).
4. Une vidéo qui arrive des minutes après le texte « Je crée ta vidéo… » est
   attendue ; une réponse faite d'une seule image est finie.

## 3. Schéma

```
app (Créer) ─┐                                    ┌─ donnees/medias/<conversation>/<id>.<ext>
API /v1/...  ─┼─ requete_creation() ─ file du Chat ─ PiloteGemini.envoyer(outil=…)
             │   (creation.py)                    │   1. coche l'outil (outils.py, au mieux)
             │                                    │   2. attend texte + médias (attente.py)
             │                                    │   3. télécharge (medias.py)
             └── garder_reponse() ◄───────────────┘      URL + cookies du Chrome dédié,
                 (reponses.py : médiathèque + historique)  « =s0 », blob:, capture
```

## 4. Ce qui change

- **Pilote** : `ResultatGemini.medias` (type, mime, octets, description) et
  `medias_perdus`. Les médias sont cherchés dans tout `model-response`
  (`img`, `video`, `audio`), hors icônes (< 64 px), avatar et sources.
  Téléchargement : requête avec les cookies du contexte (`context.request`),
  d'abord en taille réelle (`=s0` sur googleusercontent.com), puis lecture dans
  la page (`blob:`), puis capture d'écran (image). Le type vient des premiers
  octets, pas de l'en-tête ; une page HTML (connexion) ou un SVG est refusé.
- **Attente** : le nombre de médias compte comme un changement ; un média en
  préparation (barre de progression…) ou demandé mais absent fait patienter
  (`PATIENCE_MEDIAS` : 1 min image, 7 min vidéo, 4 min musique, 8 s sans outil).
- **Outil** : le menu « Outils » est ouvert et l'option qui correspond est
  cochée ; si rien n'est trouvé, la demande part sans lui. La page est rechargée
  avant le message suivant (l'outil resterait coché).
- **Stabilité** : une erreur Playwright avant l'envoi (onglet rechargé, fermé)
  donne un second essai ; après, une erreur claire (`PageInstable`), jamais un
  doublon. Une demande qui n'a pas commencé à temps est retirée de la file.
  `/api/etat` ne met plus de vérification en file derrière une longue demande.
- **Requêtes** : `creation.py` rédige la demande par type (et le format
  d'image) ; `mettre_a_plat` dit à Gemini de répondre au nouveau message sans
  préfixe ; noms de modèles à la façon des clients (« gemini-3.1-pro ») ;
  pièces jointes signalées au lieu d'être perdues en silence.
- **API** : réponse gardée dans l'historique même si le client abandonne ;
  erreurs notées ; flux SSE avec `: ping` ; CORS ; `/health` ;
  `/v1/models/{id}` ; « agent-first » dans `/v1/models`.
- **Historique** : colonne `messages.medias` (JSON), migrée à l'ouverture ;
  statistique « Médias créés ».

## 5. Sécurité

Les médias sont servis depuis l'origine de l'app (qui connaît la clé de l'API) :
`Content-Security-Policy: sandbox`, `nosniff`, jamais de SVG. Les identifiants
sont vérifiés (`<32 hex>/<12 hex>.<ext>`) : pas de chemin hors de
`donnees/medias/`. Un lien signé (HMAC de la clé) ne vaut que pour son média et
tombe quand la clé est régénérée.

## 6. À confirmer en essai réel

Sans accès à la page de Gemini pendant le travail, ces repères sont déduits et
regroupés dans `pilote/selecteurs.py` : `bouton_outils`, `OPTIONS_OUTIL`,
`HORS_MEDIAS`, `MEDIA_EN_COURS`. Vérifier avec :

```
python -m pilote.essai "Un chat roux sur un toit" --outil image
python -m pilote.essai "Une vague au ralenti" --outil video --delai 900
python -m pilote.inspecter --medias
```

Le reste (attente, téléchargement, cookies, `blob:`, taille réelle, outil
coché puis page rechargée) est vérifié dans un vrai Chromium face à une fausse
page Gemini (`tests/test_pilote_page.py`).
