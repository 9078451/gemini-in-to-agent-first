"""Ce que le pilote renvoie, et ce qu'Agent First attend d'un pilote."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResultatGemini:
    reponse: str
    adresse: str  # adresse de la conversation, ex. https://gemini.google.com/app/abc123


class Pilote(Protocol):
    def envoyer(self, adresse: str | None, texte: str) -> ResultatGemini: ...

    def est_connecte(self) -> bool: ...
