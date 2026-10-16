"""Erreurs du pilote. Le texte de chaque erreur est destiné à l'utilisateur."""


class ErreurPilote(Exception):
    """Base de toutes les erreurs du pilote navigateur."""


class ChromeInjoignable(ErreurPilote):
    def __init__(self) -> None:
        super().__init__("Impossible de joindre le Chrome dédié (port de débogage fermé).")


class PasConnecteGoogle(ErreurPilote):
    def __init__(self) -> None:
        super().__init__(
            "Connecte-toi à Google dans la fenêtre Chrome dédiée, puis renvoie ton message."
        )


class VerificationGoogle(ErreurPilote):
    def __init__(self) -> None:
        super().__init__(
            "Google demande une vérification : fais-la toi-même dans la fenêtre "
            "Chrome dédiée, puis renvoie ton message."
        )


class RepereIntrouvable(ErreurPilote):
    def __init__(self, nom: str, capture: str | None = None) -> None:
        self.nom = nom
        self.capture = capture
        message = f"Repère « {nom} » introuvable : Gemini a peut-être changé son interface."
        if capture:
            message += f" Capture d'écran : {capture}"
        super().__init__(message)


class ModeleIntrouvable(ErreurPilote):
    def __init__(self, nom: str) -> None:
        self.nom = nom
        super().__init__(f"Le modèle « {nom} » n'est pas proposé par Gemini.")


class NiveauIntrouvable(ErreurPilote):
    def __init__(self, nom: str) -> None:
        self.nom = nom
        super().__init__(f"Le niveau de réflexion « {nom} » n'est pas proposé par Gemini.")


class MessageNonEnvoye(ErreurPilote):
    def __init__(self) -> None:
        super().__init__(
            "Gemini n'a pas pris le message (connexion à Google coupée ?). "
            "Vérifie la fenêtre Chrome dédiée, puis renvoie ton message."
        )


class DelaiDepasse(ErreurPilote):
    def __init__(self, delai: float, partiel: str) -> None:
        self.partiel = partiel
        message = f"Gemini n'a pas fini de répondre après {delai:.0f} s."
        if partiel:
            message += f" Début de la réponse :\n{partiel}"
        super().__init__(message)
