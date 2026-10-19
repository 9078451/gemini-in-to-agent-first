"""Une réponse qui s'écrit, relayée vers un flux HTTP (l'app en NDJSON, l'API réseau en SSE).

`travail(au_fil)` tourne dans son propre fil : la réponse est enregistrée même si la page
ou le programme qui l'attend se déconnecte. Les morceaux arrivent au plus toutes les
`intervalle` secondes ; `arret` (bouton Arrêter) fait lever `Interrompu` au pilote.
"""
import logging
import queue
import threading
import time
from typing import Callable, Iterator

from pilote.erreurs import Interrompu

journal = logging.getLogger(__name__)

INTERVALLE = 0.15  # s : au plus un morceau de réponse par intervalle


def en_direct(
    travail: Callable[[Callable[[str, str], None]], dict],
    arret: threading.Event,
    intervalle: float = INTERVALLE,
    nom: str = "reponse",
) -> Iterator[dict]:
    """Les évènements `{"type": "partiel", "texte", "html"}`, puis l'évènement final que
    renvoie `travail` (ou `{"type": "erreur"}` s'il lève une exception inattendue)."""
    evenements: queue.Queue = queue.Queue()
    dernier = {"quand": 0.0, "texte": ""}

    def au_fil(texte: str, html: str) -> None:
        if arret.is_set():
            raise Interrompu(texte, html)
        maintenant = time.monotonic()
        if texte.strip() and texte != dernier["texte"] and maintenant - dernier["quand"] >= intervalle:
            dernier.update(quand=maintenant, texte=texte)
            evenements.put({"type": "partiel", "texte": texte, "html": html})

    def fil() -> None:
        try:
            final = travail(au_fil)
        except Exception as e:  # le flux doit toujours finir, sinon le lecteur attendrait sans fin
            journal.exception("Réponse en direct : erreur inattendue")
            final = {"type": "erreur", "code": 500, "erreur": f"Erreur inattendue : {e}"}
        evenements.put(final)

    threading.Thread(target=fil, name=nom, daemon=True).start()
    while True:
        evenement = evenements.get()
        yield evenement
        if evenement["type"] != "partiel":
            return
