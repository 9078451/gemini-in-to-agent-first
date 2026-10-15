"""Ce que le pilote renvoie, et ce qu'Agent First attend d'un pilote."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResultatGemini:
    reponse: str
    adresse: str  # adresse de la conversation, ex. https://gemini.google.com/app/abc123


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
    def envoyer(self, adresse: str | None, texte: str) -> ResultatGemini: ...

    def est_connecte(self) -> bool: ...
