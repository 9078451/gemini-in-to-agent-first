"""Ce que le pilote renvoie, et ce qu'Agent First attend d'un pilote."""
from dataclasses import dataclass
from threading import Event
from typing import Callable, Protocol

# Ce que Gemini sait créer en plus du texte : le pilote coche l'outil correspondant.
OUTILS = ("image", "video", "musique")


@dataclass(frozen=True)
class Media:
    """Une image, une vidéo ou un son de la réponse, téléchargé depuis la page."""

    type: str  # « image », « video » ou « audio »
    mime: str  # ex. image/png
    donnees: bytes
    description: str = ""  # texte alternatif lu dans la page


@dataclass(frozen=True)
class ResultatGemini:
    reponse: str
    adresse: str  # adresse de la conversation, ex. https://gemini.google.com/app/abc123
    html: str = ""
    modele: str | None = None
    niveau: str | None = None
    duree: float = 0.0  # secondes entre l'envoi et la fin de la réponse
    medias: tuple[Media, ...] = ()
    medias_perdus: int = 0  # médias vus dans la réponse mais impossibles à télécharger
    interrompue: bool = False  # arrêtée à la demande de l'utilisateur : `reponse` est le début


@dataclass(frozen=True)
class Option:
    nom: str
    description: str
    actif: bool = False


@dataclass(frozen=True)
class Modes:
    modeles: list[Option]
    niveaux: list[Option]

    @property
    def modele_actif(self) -> str | None:
        return next((o.nom for o in self.modeles if o.actif), None)

    @property
    def niveau_actif(self) -> str | None:
        return next((o.nom for o in self.niveaux if o.actif), None)


class Pilote(Protocol):
    def envoyer(
        self,
        adresse: str | None,
        texte: str,
        modele: str | None = None,
        niveau: str | None = None,
        delai: float | None = None,
        outil: str | None = None,
        pieces: tuple[Media, ...] = (),
        au_fil: Callable[[str], None] | None = None,
        arret: Event | None = None,
    ) -> ResultatGemini: ...

    def preparer(self) -> None: ...

    def est_connecte(self) -> bool: ...

    def lister_modes(self) -> Modes: ...
