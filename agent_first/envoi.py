"""Envoyer un message à l'assistant d'une conversation (Gemini, ChatGPT, Claude…) et,
avec la redondance, passer au suivant quand il est saturé, à court de crédits ou
indisponible.

Au relais, la conversation continue chez l'autre assistant : il reçoit la transcription
des échanges précédents, qu'il n'a pas vus. Partagé par le Chat de l'app et l'API réseau.
"""
import logging
import queue
import threading
import time
from concurrent.futures import CancelledError, Future
from concurrent.futures import TimeoutError as DelaiFutur
from dataclasses import dataclass, field
from typing import Callable, Iterator

from agent_first.file_attente import attendre
from agent_first.fournisseurs import Fournisseur
from agent_first.historique import Historique, Message
from agent_first.openai_compat import nettoyer_reponse
from agent_first.reglages_app import ReglagesApp
from pilote.erreurs import (
    ChoixBloque, DelaiDepasse, LimiteAtteinte, MessageAbandonne, MessageNonEnvoye, ModeleIntrouvable,
    NiveauIntrouvable, PageInstable, PasConnecteGoogle, PieceRefusee, RepereIntrouvable, VerificationGoogle,
)
from pilote.modeles import Media

journal = logging.getLogger(__name__)

# Un autre assistant peut réussir là où celui-ci échoue. Pas ChromeInjoignable : Chrome est le même pour tous.
BASCULE = (
    LimiteAtteinte, ChoixBloque, MessageNonEnvoye, MessageAbandonne, PasConnecteGoogle, VerificationGoogle,
    RepereIntrouvable, DelaiDepasse, PieceRefusee, PageInstable, ModeleIntrouvable, NiveauIntrouvable, DelaiFutur,
)
MAX_CARACTERES_RELAIS = 16000  # transcription envoyée au nouvel assistant


def peut_basculer(erreur: BaseException) -> bool:
    return isinstance(erreur, BASCULE)


def transcription(precedents: list[Message], nouveau: str) -> str:
    """Le message pour un assistant qui reprend la conversation : les échanges précédents
    (les plus récents s'il y en a trop), puis le nouveau message."""
    lignes, taille = [], 0
    for m in reversed([m for m in precedents if m.role in ("toi", "gemini") and m.texte.strip()]):
        ligne = f"{'User' if m.role == 'toi' else 'Assistant'}: {m.texte.strip()}"
        if taille + len(ligne) > MAX_CARACTERES_RELAIS:
            break
        lignes.insert(0, ligne)
        taille += len(ligne)
    if not lignes:
        return nouveau
    return (
        "[Conversation so far — you are taking over from another assistant; continue it naturally]\n"
        + "\n\n".join(lignes)
        + '\n\n[New message — answer it directly; no "Assistant:" prefix]\n'
        + nouveau
    )


@dataclass
class Tentative:
    """Un envoi à un assistant ; l'arrêt demandé par l'utilisateur ne passe jamais la main."""
    fournisseur: str
    arret: threading.Event = field(default_factory=threading.Event)
    futur: Future | None = None
    abandonnee: bool = False  # relayée à un autre assistant : sa réponse tardive n'est pas gardée
    arretee: bool = False

    def arreter(self) -> None:
        self.arretee = True
        if self.futur is None or not self.futur.cancel():
            self.arret.set()


class Repartiteur:
    def __init__(
        self,
        fournisseurs: dict[str, Fournisseur],
        historique: Historique,
        reglages: ReglagesApp,
        delai: float,
        delais_media: dict[str, float] | None = None,
        attente_file: float = 110.0,
    ) -> None:
        self.fournisseurs = fournisseurs
        self._historique = historique
        self._reglages = reglages
        self._delai = delai
        self._delais_media = delais_media or {}
        self._attente_file = attente_file

    def suivants(self, actuel: str, outil: str | None = None) -> list[str]:
        """Les autres assistants, dans l'ordre des réglages, qui savent faire la demande."""
        return [
            n for n in self._reglages.lire()["ordre"]
            if n != actuel and n in self.fournisseurs and (outil is None or outil in self.fournisseurs[n].outils)
        ]

    def limite(self, outil: str | None) -> float:
        if outil and outil in self._delais_media:
            return self._delais_media[outil] + self._attente_file
        return self._delai

    def deroulement(
        self,
        conversation_id: str,
        rediger: Callable[[str, str | None], str],
        modele: str | None = None,
        niveau: str | None = None,
        outil: str | None = None,
        pieces: tuple[Media, ...] = (),
        redondance: bool | None = None,
        apres: Callable | None = None,
        direct: bool = False,
        suivre: Callable[[Tentative], None] | None = None,
    ) -> Iterator[dict]:
        """Évènements : « texte » (si `direct`), « relais » (un autre assistant reprend), puis
        « fin » (resultat, retour de `apres(resultat, fournisseur)`, fournisseur). Lève l'erreur
        du dernier assistant essayé, ou CancelledError si l'envoi a été arrêté avant de partir.

        `rediger(fournisseur, adresse)` : le texte à envoyer (adresse None = conversation neuve
        chez cet assistant). `suivre(tentative)` : pour pouvoir l'arrêter."""
        if redondance is None:
            redondance = self._reglages.lire()["redondance"]
        conversation = self._historique.conversation(conversation_id)
        actuel = conversation.fournisseur if conversation.fournisseur in self.fournisseurs else next(iter(self.fournisseurs))
        essais = [actuel] + (self.suivants(actuel, outil) if redondance else [])
        adresse = conversation.adresse
        limite = self.limite(outil)
        for rang, nom in enumerate(essais):
            f = self.fournisseurs[nom]
            if rang:
                self._historique.basculer(conversation_id, nom)
                adresse, modele, niveau = None, None, None
            tentative = Tentative(nom)
            ecrit: queue.Queue = queue.Queue()
            options: dict = {"arret": tentative.arret}
            if outil:
                options |= {"outil": outil, "delai": self._delais_media.get(outil)}
            if pieces:
                options["pieces"] = tuple(pieces)
            if direct:
                options["au_fil"] = lambda brut: ecrit.put(nettoyer_reponse(brut))
            texte = rediger(nom, adresse)

            def travail(pilote, tentative=tentative, texte=texte, adresse=adresse, modele=modele, niveau=niveau,
                        options=options, nom=nom):
                resultat = pilote.envoyer(adresse, texte, modele, niveau, **options)
                if tentative.abandonnee:  # un autre assistant a déjà pris le relais
                    return resultat, None
                return resultat, (apres(resultat, nom) if apres else None)

            tentative.futur = f.file_chat.soumettre(travail)
            if suivre is not None:
                suivre(tentative)
            try:
                if direct:
                    fin, dernier = time.monotonic() + limite, None
                    while True:
                        try:
                            texte_lu = ecrit.get(timeout=0.1)
                        except queue.Empty:
                            texte_lu = None
                        if texte_lu is not None:
                            if texte_lu != dernier:
                                dernier = texte_lu
                                yield {"type": "texte", "texte": texte_lu, "fournisseur": nom}
                            continue
                        # File vide : l'assistant écrit tout avant de rendre son résultat, donc rien n'est perdu.
                        if tentative.futur.done():
                            resultat, retour = tentative.futur.result()
                            break
                        if time.monotonic() >= fin:
                            tentative.futur.cancel()
                            raise DelaiFutur()
                else:
                    resultat, retour = attendre(tentative.futur, limite)
            except CancelledError:
                raise
            except Exception as e:
                if rang + 1 < len(essais) and peut_basculer(e) and not tentative.arretee:
                    tentative.abandonnee = True
                    tentative.arret.set()  # s'il écrit encore, qu'il s'arrête
                    suivant = self.fournisseurs[essais[rang + 1]].libelle
                    journal.info("Redondance : %s → %s (%s)", f.libelle, suivant, e)
                    yield {"type": "relais", "de": f.libelle, "vers": suivant, "fournisseur": essais[rang + 1],
                           "raison": str(e)}
                    continue
                raise
            yield {"type": "fin", "resultat": resultat, "retour": retour, "fournisseur": nom}
            return

    def envoyer(self, conversation_id: str, rediger: Callable[[str, str | None], str], **options) -> dict:
        """Comme `deroulement`, sans le direct : renvoie l'évènement « fin » (avec la liste des
        relais en plus)."""
        relais = []
        for evenement in self.deroulement(conversation_id, rediger, **options):
            if evenement["type"] == "relais":
                relais.append(evenement)
            elif evenement["type"] == "fin":
                return {**evenement, "relais": relais}
        raise RuntimeError("déroulement sans fin")
