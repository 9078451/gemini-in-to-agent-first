"""La clé de l'API réseau : créée au premier lancement, gardée dans `donnees/`,
exigée sur chaque appel. Trop d'essais faux depuis une même adresse la bloquent
un moment (on ne devine pas une clé en essayant en boucle).

Elle signe aussi les liens des médias : un lien signé s'ouvre sans en-tête (balise
<img>, navigateur, lecteur vidéo) mais ne donne accès qu'à ce média, et cesse de
marcher quand la clé est régénérée.
"""
import hashlib
import hmac
import secrets
import threading
import time
from pathlib import Path
from typing import Callable


def lire_ou_creer_cle(fichier: Path) -> str:
    if fichier.is_file():
        cle = fichier.read_text(encoding="utf-8").strip()
        if cle:
            return cle
    return _ecrire(fichier, secrets.token_urlsafe(32))


def _ecrire(fichier: Path, cle: str) -> str:
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(cle + "\n", encoding="utf-8")
    return cle


class GardeCle:
    def __init__(
        self,
        fichier: Path,
        essais_max: int = 10,
        fenetre: float = 60.0,
        blocage: float = 60.0,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fichier = fichier
        self._cle = lire_ou_creer_cle(fichier)
        self._essais_max = essais_max
        self._fenetre = fenetre
        self._blocage = blocage
        self._horloge = horloge
        self._echecs: dict[str, list[float]] = {}
        self._bloques: dict[str, float] = {}  # adresse → fin du blocage
        self._verrou = threading.Lock()

    @property
    def cle(self) -> str:
        return self._cle

    def regenerer(self) -> str:
        with self._verrou:
            self._cle = _ecrire(self._fichier, secrets.token_urlsafe(32))
            return self._cle

    def verifier(self, adresse: str, entete: str | None) -> int | None:
        """None si la clé est bonne ; sinon le code HTTP à renvoyer (401, ou 429 si bloqué)."""
        maintenant = self._horloge()
        with self._verrou:
            fin_blocage = self._bloques.get(adresse)
            if fin_blocage is not None:
                if maintenant < fin_blocage:
                    return 429
                del self._bloques[adresse]
            fournie = entete[7:].strip() if entete and entete[:7].lower() == "bearer " else ""
            if fournie and hmac.compare_digest(fournie.encode(), self._cle.encode()):
                return None
            recents = [t for t in self._echecs.get(adresse, []) if maintenant - t < self._fenetre]
            recents.append(maintenant)
            if len(recents) >= self._essais_max:
                self._bloques[adresse] = maintenant + self._blocage
                recents = []
            self._echecs[adresse] = recents
            return 401

    def signer(self, chemin: str) -> str:
        """La signature d'un lien (« <conversation>/<fichier> ») : sans elle, le lien exige la clé."""
        return hmac.new(self._cle.encode(), chemin.encode(), hashlib.sha256).hexdigest()[:32]

    def signature_valide(self, chemin: str, signature: str | None) -> bool:
        return bool(signature) and hmac.compare_digest(signature.encode(), self.signer(chemin).encode())
