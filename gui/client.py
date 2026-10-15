"""Parler à Agent First par HTTP."""
import httpx


class ErreurClient(Exception):
    """Erreur à afficher telle quelle dans la fenêtre."""


class ClientAgentFirst:
    def __init__(self, url_base: str, delai: float, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(base_url=url_base, timeout=delai, transport=transport)
        self._delai = delai

    def nouvelle_conversation(self) -> str:
        return self._appeler("POST", "/conversations")["conversation"]

    def envoyer(self, conversation: str, texte: str) -> str:
        contenu = self._appeler("POST", "/message", json={"conversation": conversation, "texte": texte})
        return contenu["reponse"]

    def etat(self) -> dict:
        return self._appeler("GET", "/etat")

    def _appeler(self, methode: str, chemin: str, **options) -> dict:
        try:
            reponse = self._http.request(methode, chemin, **options)
        except httpx.ConnectError as e:
            raise ErreurClient("Agent First n'est pas démarré.") from e
        except httpx.TimeoutException as e:
            raise ErreurClient(f"Pas de réponse d'Agent First après {self._delai / 60:.0f} minutes.") from e
        try:
            contenu = reponse.json()
        except ValueError:
            contenu = {}
        if reponse.is_error:
            raise ErreurClient(contenu.get("erreur") or f"Erreur d'Agent First (code {reponse.status_code}).")
        return contenu
