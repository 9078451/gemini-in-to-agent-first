"""Attendre que Gemini prenne un message, puis que sa réponse ait fini de s'écrire."""
import time
from typing import Callable

from pilote.erreurs import DelaiDepasse, MessageNonEnvoye


def attendre_envoi(
    compter_questions: Callable[[], int],
    nb_avant: int,
    delai: float,
    intervalle: float = 0.5,
    horloge: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> None:
    """Attend que la question apparaisse dans la conversation. Sinon (réseau
    coupé, clic ignoré), lève MessageNonEnvoye après `delai` au lieu de laisser
    attendre une réponse qui ne viendra jamais."""
    fin = horloge() + delai
    while horloge() < fin:
        if compter_questions() > nb_avant:
            return
        dormir(intervalle)
    raise MessageNonEnvoye()


def attendre_fin_reponse(
    lire_texte: Callable[[], str],
    generation_en_cours: Callable[[], bool],
    delai_max: float,
    stabilite: float,
    intervalle: float = 0.5,
    horloge: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> str:
    """Renvoie le texte quand la génération est finie et que le texte n'a plus
    bougé pendant `stabilite` secondes. Lève DelaiDepasse après `delai_max`."""
    debut = horloge()
    dernier_texte = lire_texte()
    dernier_changement = debut
    while True:
        maintenant = horloge()
        if maintenant - debut > delai_max:
            raise DelaiDepasse(delai_max, dernier_texte.strip())
        texte = lire_texte()
        if texte != dernier_texte:
            dernier_texte = texte
            dernier_changement = maintenant
        elif (
            texte.strip()
            and not generation_en_cours()
            and maintenant - dernier_changement >= stabilite
        ):
            return texte
        dormir(intervalle)
