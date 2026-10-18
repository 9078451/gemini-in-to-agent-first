"""Les réglages d'Agent First gardés sur le PC (Paramètres de l'app) : la redondance et
l'ordre des assistants. Valent pour l'app et pour l'API réseau."""
import json
import logging
import os
import threading
from pathlib import Path

journal = logging.getLogger(__name__)


class ReglagesApp:
    def __init__(self, fichier: Path | None, fournisseurs: list[str], redondance: bool = False) -> None:
        """`fichier` None : réglages gardés en mémoire seulement."""
        self._fichier = fichier
        self._fournisseurs = list(fournisseurs)
        self._verrou = threading.Lock()
        self._valeurs = {"redondance": redondance, "ordre": list(fournisseurs)}
        if fichier is None:
            return
        try:
            lus = json.loads(fichier.read_text(encoding="utf-8"))
            self._valeurs = self._valider(lus.get("redondance", redondance), lus.get("ordre"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            journal.warning("%s illisible : réglages par défaut", fichier)

    def lire(self) -> dict:
        with self._verrou:
            return {"redondance": self._valeurs["redondance"], "ordre": list(self._valeurs["ordre"])}

    def ecrire(self, redondance: bool | None = None, ordre: list[str] | None = None) -> dict:
        with self._verrou:
            self._valeurs = self._valider(
                self._valeurs["redondance"] if redondance is None else redondance,
                self._valeurs["ordre"] if ordre is None else ordre,
            )
            if self._fichier is None:
                return {"redondance": self._valeurs["redondance"], "ordre": list(self._valeurs["ordre"])}
            self._fichier.parent.mkdir(parents=True, exist_ok=True)
            provisoire = self._fichier.with_suffix(".tmp")
            provisoire.write_text(json.dumps(self._valeurs, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(provisoire, self._fichier)
            return {"redondance": self._valeurs["redondance"], "ordre": list(self._valeurs["ordre"])}

    def _valider(self, redondance, ordre) -> dict:
        """L'ordre ne garde que les assistants connus, sans doublon ; les oubliés vont à la fin."""
        connus = [n for n in dict.fromkeys(ordre or []) if n in self._fournisseurs]
        return {"redondance": bool(redondance), "ordre": connus + [n for n in self._fournisseurs if n not in connus]}
