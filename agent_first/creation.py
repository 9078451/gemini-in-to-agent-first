"""Créer des images, des vidéos et de la musique avec Gemini.

La demande de l'utilisateur part rédigée pour que Gemini crée vraiment le média : sans
consigne, il lui arrive de le décrire, ou d'écrire un « prompt » à copier ailleurs.
L'historique garde la demande telle que l'utilisateur l'a écrite.
"""
import re

CONSIGNES = {
    "image": "Génère une image pour la demande ci-dessous. Réponds avec l'image elle-même "
             "(pas une description, pas un prompt à copier), et une phrase de commentaire au plus.",
    "video": "Génère une vidéo avec Veo pour la demande ci-dessous. Réponds avec la vidéo elle-même "
             "(pas un script, pas une description).",
    "musique": "Génère un morceau de musique (un fichier audio) pour la demande ci-dessous. Réponds avec "
               "l'audio lui-même (pas seulement des paroles, pas une partition).",
}
SUITE = "Si la demande porte sur un média précédent de cette conversation, modifie-le au lieu d'en créer un sans rapport."
FORMATS = {"carre": "format carré (1:1)", "paysage": "format paysage (16:9)", "portrait": "format portrait (9:16)"}
VARIANTE = {
    "image": "Génère une autre version de cette image, différente des précédentes, pour la même demande.",
    "video": "Génère une autre version de cette vidéo, différente des précédentes, pour la même demande.",
    "musique": "Génère une autre version de ce morceau, différente des précédentes, pour la même demande.",
}
# Ce que l'API réseau accepte pour désigner un outil (format OpenAI, OpenRouter, français…).
ALIAS = {
    "image": "image", "images": "image", "photo": "image", "picture": "image",
    "video": "video", "vidéo": "video", "videos": "video",
    "musique": "musique", "music": "musique", "audio": "musique", "song": "musique", "chanson": "musique",
}
TYPE_MEDIA = {"image": "image", "video": "video", "musique": "audio"}  # type du média attendu


def requete_creation(outil: str, demande: str, format: str | None = None, suite: bool = False) -> str:
    """Le message envoyé à Gemini pour créer un média. `suite` : la conversation Gemini
    existe déjà (la demande peut viser un média précédent)."""
    consigne = CONSIGNES[outil]
    if format in FORMATS:
        consigne += f" Format : {FORMATS[format]}."
    if suite:
        consigne += " " + SUITE
    return f"{consigne}\n\nDemande : {demande.strip()}"


def outil_depuis(valeur: str | None) -> str | None:
    """« image », « video », « musique » d'après un nom libre, ou None."""
    return ALIAS.get(valeur.strip().lower()) if isinstance(valeur, str) else None


def format_depuis_taille(taille: str | None) -> str | None:
    """« 1792x1024 » (format OpenAI) → « paysage » ; « auto », vide ou illisible → None."""
    trouve = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", taille or "")
    if not trouve:
        return None
    largeur, hauteur = int(trouve.group(1)), int(trouve.group(2))
    return "carre" if largeur == hauteur else "paysage" if largeur > hauteur else "portrait"

