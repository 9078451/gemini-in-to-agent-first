"""Envoyer un message du Chat (app ou API réseau) au bon fournisseur, et l'enregistrer.

- Le fournisseur demandé n'est pas celui de la conversation (l'utilisateur en a choisi un
  autre) : il n'a pas l'historique ; le message part « à plat », avec les échanges
  précédents, dans une conversation neuve chez lui.
- Le fournisseur est à sa limite ou en panne (erreur `secours`) et un secours est réglé :
  la demande repart chez le secours, à plat, et la conversation y continue.
- `au_fil(texte, html)` reçoit la réponse pendant qu'elle s'écrit ; `arret` l'interrompt
  (ce qui est écrit est gardé).
"""
import json
import logging
import threading
import time
from concurrent.futures import TimeoutError as DelaiFutur
from dataclasses import asdict
from typing import Callable

from agent_first.historique import ConversationInconnue, Historique
from agent_first.nettoyage import nettoyer_html
from agent_first.openai_compat import mettre_a_plat, nettoyer_reponse
from fournisseurs.catalogue import MODELE_SITE
from fournisseurs.etats import classer
from fournisseurs.repartiteur import FournisseurInconnu
from fournisseurs.service import ServiceFournisseurs
from pilote.chrome import ONGLET_CHAT
from pilote.erreurs import ChoixBloque, ErreurPilote, Interrompu, ModeleIntrouvable, NiveauIntrouvable
from pilote.modeles import ResultatGemini

journal = logging.getLogger(__name__)

ROLES_OPENAI = {"toi": "user", "gemini": "assistant"}


class AttenteTropLongue(ErreurPilote):
    secours = True

    def __init__(self, nom: str, delai: float) -> None:
        super().__init__(f"Pas de réponse de {nom} après {delai:.0f} s.")


class EchecEnvoi(Exception):
    """L'envoi a échoué ; l'erreur est déjà enregistrée dans la conversation."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def echanges(messages) -> list[dict]:
    """Les messages enregistrés au format OpenAI (questions et réponses seulement)."""
    return [{"role": ROLES_OPENAI[m.role], "content": m.texte} for m in messages if m.role in ROLES_OPENAI]


def a_plat(precedents: list[dict], nouveau: str) -> str:
    return mettre_a_plat(precedents + [{"role": "user", "content": nouveau}]) if precedents else nouveau


class ServiceChat:
    def __init__(
        self,
        historique: Historique,
        fournisseurs: ServiceFournisseurs,
        delai: float,
        noter: Callable[[str, Exception | None], None] | None = None,
    ) -> None:
        self._historique = historique
        self._fournisseurs = fournisseurs
        self._delai = delai
        self._noter_externe = noter

    def envoyer(
        self,
        conversation_id: str,
        texte: str,
        fournisseur: str | None = None,
        modele: str | None = None,
        niveau: str | None = None,
        au_fil: Callable[[str, str], None] | None = None,
        arret: threading.Event | None = None,
        texte_pilote: str | None = None,
    ) -> dict:
        """Renvoie le message de réponse enregistré (dict). Lève ConversationInconnue, ou
        EchecEnvoi (code HTTP, message) une fois l'erreur enregistrée."""
        conversation = self._historique.conversation(conversation_id)
        fournisseur = fournisseur or conversation.fournisseur
        precedents = echanges(self._historique.messages(conversation_id))
        self._historique.ajouter_message(conversation_id, "toi", texte, modele=modele, niveau=niveau,
                                         fournisseur=fournisseur)
        a_envoyer = texte_pilote or texte
        if fournisseur != conversation.fournisseur:
            self._historique.changer_fournisseur(conversation_id, fournisseur, modele, niveau)
            adresse, a_envoyer = None, a_plat(precedents, a_envoyer)
        else:
            adresse = conversation.adresse
        debut = time.monotonic()
        details = None
        try:
            resultat = self._tenter(fournisseur, adresse, a_envoyer, modele, niveau, au_fil, arret)
        except Interrompu as e:
            return self._partiel(conversation_id, fournisseur, modele, niveau, e, debut)
        except ErreurPilote as e:
            secours = self._fournisseurs.secours()
            if not (e.secours and secours and secours["fournisseur"] != fournisseur):
                raise self._echec(conversation_id, fournisseur, e)
            de, fournisseur, modele = fournisseur, secours["fournisseur"], secours["modele"]
            niveau = niveau if self._fournisseurs.a_des_niveaux(fournisseur) else None
            journal.info("%s indisponible (%s) : secours %s", de, e, fournisseur)
            self._historique.changer_fournisseur(conversation_id, fournisseur, modele, niveau)
            details = {"secours": {"de": de, "raison": classer(e) or "panne", "message": str(e)}}
            try:
                resultat = self._tenter(fournisseur, None, a_plat(precedents, texte_pilote or texte), modele, niveau,
                                        au_fil, arret)
            except Interrompu as e2:
                return self._partiel(conversation_id, fournisseur, modele, niveau, e2, debut, details)
            except ErreurPilote as e2:
                raise self._echec(conversation_id, fournisseur, e2, avant=(de, e))
            except Exception as e2:
                raise self._inattendue(conversation_id, fournisseur, e2)
        except Exception as e:
            raise self._inattendue(conversation_id, fournisseur, e)
        return self._enregistrer(conversation_id, fournisseur, resultat, details)

    def _inattendue(self, conversation_id: str, fournisseur: str, e: Exception) -> EchecEnvoi:
        journal.error("Erreur inattendue pendant l'envoi", exc_info=e)
        return self._echec(conversation_id, fournisseur, e, code=500, message=f"Erreur inattendue : {e}")

    # ---- interne ----------------------------------------------------------

    def _tenter(self, fournisseur, adresse, texte, modele, niveau, au_fil, arret) -> ResultatGemini:
        if not self._fournisseurs.est_actif(fournisseur):
            raise FournisseurInconnu(fournisseur)
        modele_pilote = None if modele == MODELE_SITE else modele

        def travail(pilote):
            if arret is not None and arret.is_set():  # arrêté pendant qu'il attendait son tour
                raise Interrompu()
            if au_fil is None:
                return pilote.envoyer(adresse, texte, modele_pilote, niveau)
            return pilote.envoyer(adresse, texte, modele_pilote, niveau, au_fil=au_fil)

        futur = self._fournisseurs.repartiteur.file(fournisseur, ONGLET_CHAT).soumettre(travail)
        try:
            resultat = futur.result(timeout=self._delai)
        except DelaiFutur:
            futur.cancel()
            if arret is not None:
                arret.set()  # que le fournisseur s'arrête aussi : la réponse ne sera plus attendue
            erreur = AttenteTropLongue(self._fournisseurs.nom(fournisseur), self._delai)
            self._noter(fournisseur, erreur)
            raise erreur
        except ErreurPilote as e:
            self._noter(fournisseur, e)
            if isinstance(e, (ModeleIntrouvable, NiveauIntrouvable, ChoixBloque)):
                self._fournisseurs.oublier_modeles(fournisseur)  # la liste a changé : relue à la prochaine demande
            raise
        self._noter(fournisseur, None)
        return resultat

    def _noter(self, fournisseur: str, erreur: Exception | None) -> None:
        if erreur is None:
            self._fournisseurs.etats.noter_ok(fournisseur)
        elif not isinstance(erreur, Interrompu):
            self._fournisseurs.etats.noter_erreur(fournisseur, erreur)
        if self._noter_externe is not None:
            self._noter_externe(fournisseur, erreur)

    def _enregistrer(self, conversation_id: str, fournisseur: str, resultat: ResultatGemini,
                     details: dict | None) -> dict:
        html = nettoyer_html(resultat.html) if resultat.html else None
        texte_details = json.dumps(details, ensure_ascii=False) if details else None
        try:
            if resultat.adresse:
                self._historique.enregistrer_adresse(conversation_id, resultat.adresse)
            message = self._historique.ajouter_message(
                conversation_id, "gemini", nettoyer_reponse(resultat.reponse), html=html, modele=resultat.modele,
                niveau=resultat.niveau, duree=resultat.duree, details=texte_details, fournisseur=fournisseur,
            )
        except ConversationInconnue:
            journal.info("Conversation %s supprimée pendant l'envoi : réponse non enregistrée", conversation_id)
            return {
                "id": None, "conversation_id": conversation_id, "role": "gemini", "texte": nettoyer_reponse(resultat.reponse),
                "html": html, "modele": resultat.modele, "niveau": resultat.niveau, "duree": resultat.duree,
                "details": texte_details, "fournisseur": fournisseur, "cree_le": None,
            }
        return asdict(message)

    def _partiel(self, conversation_id, fournisseur, modele, niveau, e: Interrompu, debut: float,
                 details: dict | None = None) -> dict:
        if not e.partiel:
            raise self._echec(conversation_id, fournisseur, e, code=499, message="Réponse arrêtée avant son début.")
        resultat = ResultatGemini(e.partiel, e.adresse or "", e.html, None if modele == MODELE_SITE else modele,
                                  niveau, round(time.monotonic() - debut, 1))
        return self._enregistrer(conversation_id, fournisseur, resultat, {**(details or {}), "interrompue": True})

    def _echec(self, conversation_id: str, fournisseur: str, e: Exception, avant=None, code: int | None = None,
               message: str | None = None) -> EchecEnvoi:
        if message is None:
            message = str(e)
            if avant is not None:
                de, erreur_de = avant
                message = (f"{self._fournisseurs.nom(de)} : {erreur_de}\n"
                           f"Secours ({self._fournisseurs.nom(fournisseur)}) : {e}")
        if code is None:
            code = 400 if isinstance(e, FournisseurInconnu) else 504 if isinstance(e, AttenteTropLongue) else 502
        try:
            self._historique.ajouter_message(conversation_id, "erreur", message)
        except ConversationInconnue:
            pass
        return EchecEnvoi(code, message)
