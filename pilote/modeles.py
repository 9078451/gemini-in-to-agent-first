"""Ce que le pilote renvoie, et ce qu'Agent First attend d'un pilote."""
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class ResultatGemini:
    reponse: str
    adresse: str  # adresse de la conversation, ex. https://gemini.google.com/app/abc123
    html: str = ""
    modele: str | None = None
    niveau: str | None = None
    duree: float = 0.0  # secondes entre l'envoi et la fin de la réponse


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
    """Un fournisseur d'IA : un site piloté dans Chrome (Gemini, ChatGPT, Claude.ai) ou une API.

    `adresse` : la conversation chez ce fournisseur (URL du site, ou `api:<id>`), None pour
    une nouvelle. `au_fil(texte, html)` reçoit la réponse pendant qu'elle s'écrit ; s'il
    lève `Interrompu`, le pilote arrête la réponse et l'erreur remonte avec le texte partiel."""

    def envoyer(
        self,
        adresse: str | None,
        texte: str,
        modele: str | None = None,
        niveau: str | None = None,
        delai: float | None = None,
        au_fil: Callable[[str, str], None] | None = None,
    ) -> ResultatGemini: ...

    def preparer(self) -> None: ...

    def est_connecte(self) -> bool: ...

    def lister_modes(self) -> Modes: ...
