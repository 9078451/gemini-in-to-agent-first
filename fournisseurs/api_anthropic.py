"""Pilote de Claude par clé API, avec le SDK officiel `anthropic`.

La réponse arrive en flux (`messages.stream`) ; la réflexion est adaptative (par défaut sur
les modèles actuels) et le niveau choisi devient `output_config.effort`. `fallbacks:
"default"` : si le modèle refuse une demande pour ses règles de sécurité, l'API la relance
sur le modèle de repli prévu ; sans repli possible, la demande reste refusée et l'app le dit.
Le SDK réessaie lui-même deux fois une limite (429) ou une panne (5xx).
"""
import logging
import time
from typing import Callable

import anthropic

from fournisseurs.commun import EFFORTS, NIVEAUX, Ecriture, modele_choisi
from fournisseurs.memoire import MemoireFils
from fournisseurs.reglages import ReglagesFournisseurs
from pilote.erreurs import (
    CleRefusee, DemandeRefusee, FournisseurIndisponible, Interrompu, LimiteFournisseur, ModeleIntrouvable,
)
from pilote.modeles import Modes, Option, ResultatGemini

journal = logging.getLogger(__name__)

ID = "anthropic"
NOM = "Claude"
MAX_TOKENS = 64000  # en flux : pas de délai HTTP à craindre, de la place pour répondre
BETAS = ["server-side-fallback-2026-07-01"]
DELAI_DEFAUT = 600.0


def traduire(erreur: Exception, modele: str, partiel: str = "") -> Exception:
    """Une erreur du SDK → l'erreur d'Agent First à montrer (en français, avec quoi faire)."""
    if isinstance(erreur, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return CleRefusee(NOM)
    if isinstance(erreur, anthropic.NotFoundError):
        return ModeleIntrouvable(modele, NOM)
    if isinstance(erreur, anthropic.RateLimitError):
        return LimiteFournisseur(NOM, getattr(erreur, "message", str(erreur)))
    if isinstance(erreur, anthropic.BadRequestError):
        return DemandeRefusee(NOM, getattr(erreur, "message", str(erreur)))
    if isinstance(erreur, anthropic.APIStatusError):
        return FournisseurIndisponible(NOM, f"erreur {erreur.status_code}", partiel)
    if isinstance(erreur, anthropic.APITimeoutError):
        return FournisseurIndisponible(NOM, "pas de réponse dans le délai", partiel)
    if isinstance(erreur, anthropic.APIConnectionError):
        return FournisseurIndisponible(NOM, "connexion impossible ou coupée", partiel)
    return erreur


class PiloteClaudeAPI:
    def __init__(
        self,
        reglages: ReglagesFournisseurs,
        memoire: MemoireFils,
        fabrique_client: Callable[[str], object] | None = None,
    ) -> None:
        self._reglages = reglages
        self._memoire = memoire
        self._fabrique = fabrique_client or (lambda cle: anthropic.Anthropic(api_key=cle, max_retries=2))
        self._clients: dict[str, object] = {}  # par clé : une clé changée dans Paramètres sert aussitôt
        self._lus: list[str] = []

    # ---- contrat Pilote ---------------------------------------------------

    def preparer(self) -> None:
        pass

    def est_connecte(self) -> bool:
        return bool(self._reglages.cle(ID))

    def lister_modes(self) -> Modes:
        modeles = self.lister_modeles()
        return Modes([Option(m, "", i == 0) for i, m in enumerate(modeles)], NIVEAUX)

    def lister_modeles(self) -> list[str]:
        try:
            self._lus = [m.id for m in self._client().models.list(limit=100)]
        except anthropic.APIError as e:
            raise traduire(e, "") from e
        return self._lus

    def envoyer(
        self,
        adresse: str | None,
        texte: str,
        modele: str | None = None,
        niveau: str | None = None,
        delai: float | None = None,
        au_fil: Callable[[str, str], None] | None = None,
    ) -> ResultatGemini:
        debut = time.monotonic()
        modele = modele_choisi(ID, self._reglages, modele, self._lus)
        messages = self._memoire.lire(adresse) + [{"role": "user", "content": texte}]
        adresse = adresse or self._memoire.nouvelle_adresse(ID)
        parametres = {"model": modele, "max_tokens": MAX_TOKENS, "messages": messages,
                      "betas": BETAS, "fallbacks": "default"}
        if niveau in EFFORTS:
            parametres["output_config"] = {"effort": EFFORTS[niveau]}
        ecriture = Ecriture(au_fil)
        client = self._client().with_options(timeout=delai or DELAI_DEFAUT)
        try:
            with client.beta.messages.stream(**parametres) as flux:
                for evenement in flux:
                    if evenement.type == "text":
                        ecriture.ajouter(evenement.text)
                    else:
                        ecriture.verifier()  # réflexion, signal de maintien : un arrêt demandé est vu
                final = flux.get_final_message()
        except Interrompu:
            if ecriture.texte:
                self._memoire.ecrire(adresse, messages + [{"role": "assistant", "content": ecriture.texte}])
            raise Interrompu(ecriture.texte, ecriture.html_final(), adresse)
        except anthropic.APIError as e:
            raise traduire(e, modele, ecriture.texte) from e
        if final.stop_reason == "refusal" and not ecriture.texte.strip():
            raise DemandeRefusee(NOM, "la demande a été refusée par les règles de sécurité de Claude.")
        self._memoire.ecrire(adresse, messages + [{"role": "assistant", "content": ecriture.texte}])
        if final.stop_reason == "max_tokens":
            journal.info("Réponse de Claude coupée à %d jetons", MAX_TOKENS)
        return ResultatGemini(
            reponse=ecriture.texte.strip(), adresse=adresse, html=ecriture.html_final(),
            modele=getattr(final, "model", None) or modele, niveau=niveau if niveau in EFFORTS else None,
            duree=round(time.monotonic() - debut, 1),
        )

    # ---- interne ----------------------------------------------------------

    def _client(self):
        cle = self._reglages.cle(ID)
        if not cle:
            raise CleRefusee(NOM)
        if cle not in self._clients:
            self._clients = {cle: self._fabrique(cle)}
        return self._clients[cle]
