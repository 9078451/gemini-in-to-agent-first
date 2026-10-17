"""Attendre que Gemini prenne un message, puis que sa réponse ait fini de s'écrire."""
import time
from typing import Callable

from pilote.erreurs import DelaiDepasse, ErreurPilote, LimiteGemini, MessageAbandonne, MessageNonEnvoye


def erreur_envoi(bandeau_limite: str | None) -> ErreurPilote:
    """L'erreur à montrer quand Gemini n'a pas pris le message : la limite
    d'utilisation du compte si Gemini l'affiche, sinon une cause inconnue."""
    return LimiteGemini(bandeau_limite) if bandeau_limite else MessageNonEnvoye()


def attendre_envoi(
    compter_questions: Callable[[], int],
    nb_avant: int,
    delai: float,
    lire_bandeau_limite: Callable[[], str | None] = lambda: None,
    intervalle: float = 0.5,
    horloge: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> None:
    """Attend que la question apparaisse dans la conversation. Sinon (limite
    d'utilisation, réseau coupé, clic ignoré), lève une erreur après `delai`
    au lieu de laisser attendre une réponse qui ne viendra jamais."""
    fin = horloge() + delai
    while horloge() < fin:
        if compter_questions() > nb_avant:
            return
        dormir(intervalle)
    raise erreur_envoi(lire_bandeau_limite())


def attendre_nouvelle_reponse(
    compter_reponses: Callable[[], int],
    compter_questions: Callable[[], int],
    generation_en_cours: Callable[[], bool],
    nb_reponses_avant: int,
    nb_questions_attendu: int,
    delai: float,
    patience_abandon: float = 8.0,
    intervalle: float = 0.3,
    horloge: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> bool:
    """True dès qu'une nouvelle réponse apparaît ; False après `delai` sans réponse ni
    génération. DelaiDepasse si Gemini génère encore au bout du délai. MessageAbandonne si
    la question a disparu et que plus rien ne se génère depuis `patience_abandon` secondes :
    Gemini a lâché le message, inutile d'attendre la fin du délai (jusqu'à 10 min)."""
    fin = horloge() + delai
    disparue_depuis = None
    while horloge() < fin:
        if compter_reponses() > nb_reponses_avant:
            return True
        if compter_questions() < nb_questions_attendu and not generation_en_cours():
            # Un court trou est normal (la page se redessine en passant à /app/<id>).
            disparue_depuis = disparue_depuis if disparue_depuis is not None else horloge()
            if horloge() - disparue_depuis >= patience_abandon:
                raise MessageAbandonne()
        else:
            disparue_depuis = None
        dormir(intervalle)
    if generation_en_cours():
        raise DelaiDepasse(delai, "")
    return False


def attendre_fin_reponse(
    lire_texte: Callable[[], str],
    generation_en_cours: Callable[[], bool],
    delai_max: float,
    stabilite: float,
    intervalle: float = 0.5,
    horloge: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
    stabilite_apres_generation: float = 0.6,
) -> str:
    """Renvoie le texte quand la génération est finie et que le texte n'a plus bougé
    pendant `stabilite` secondes — ou seulement `stabilite_apres_generation` si on a vu
    Gemini générer puis s'arrêter : ce signal est sûr, inutile d'attendre 2 s à chaque
    réponse. Lève DelaiDepasse après `delai_max`."""
    debut = horloge()
    dernier_texte = lire_texte()
    dernier_changement = debut
    vu_generer = False
    while True:
        maintenant = horloge()
        if maintenant - debut > delai_max:
            raise DelaiDepasse(delai_max, dernier_texte.strip())
        texte = lire_texte()
        en_cours = generation_en_cours()
        vu_generer = vu_generer or en_cours
        attente = stabilite_apres_generation if vu_generer else stabilite
        if texte != dernier_texte:
            dernier_texte = texte
            dernier_changement = maintenant
        elif texte.strip() and not en_cours and maintenant - dernier_changement >= attente:
            return texte
        dormir(intervalle)
