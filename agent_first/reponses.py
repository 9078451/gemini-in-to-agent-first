"""Garder une réponse de Gemini : ses médias sur le disque, le message dans l'historique.

Partagé par le Chat de l'app et l'API réseau.
"""
import json
import logging

from agent_first.historique import ConversationInconnue, Historique, Message
from agent_first.mediatheque import Mediatheque
from agent_first.openai_compat import nettoyer_reponse
from pilote.modeles import ResultatGemini

journal = logging.getLogger(__name__)


def garder_reponse(
    historique: Historique,
    mediatheque: Mediatheque | None,
    conversation_id: str,
    resultat: ResultatGemini,
    html: str | None = None,
    fournisseur: str | None = None,
) -> tuple[Message | None, list[dict]]:
    """Le message enregistré (None si la conversation a été retirée pendant l'envoi, ou si
    la réponse a été arrêtée avant que Gemini écrive quoi que ce soit) et la description
    des médias."""
    if resultat.interrompue and not resultat.reponse.strip() and not resultat.medias:
        return None, []
    decrits = []
    if mediatheque is not None and resultat.medias:
        try:
            decrits = mediatheque.enregistrer(conversation_id, resultat.medias)
        except OSError:
            journal.exception("Médias de la réponse non enregistrés")
    try:
        historique.enregistrer_adresse(conversation_id, resultat.adresse)
        message = historique.ajouter_message(
            conversation_id, "gemini", nettoyer_reponse(resultat.reponse), html=html,
            modele=resultat.modele, niveau=resultat.niveau, duree=resultat.duree, medias=decrits,
            details=_details(resultat, fournisseur),
        )
    except ConversationInconnue:
        journal.info("Conversation %s retirée pendant l'envoi : réponse non enregistrée", conversation_id)
        if mediatheque is not None:
            mediatheque.supprimer(conversation_id)
        return None, decrits
    return message, decrits


def _details(resultat: ResultatGemini, fournisseur: str | None) -> str | None:
    """L'assistant qui a répondu (« chatgpt »…) et si la réponse a été arrêtée."""
    details = {}
    if fournisseur and fournisseur != "gemini":
        details["fournisseur"] = fournisseur
    if resultat.interrompue:
        details["interrompue"] = True
    return json.dumps(details) if details else None
