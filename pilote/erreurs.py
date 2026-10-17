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


class MessageAbandonne(ErreurPilote):
    """Gemini a pris le message, réfléchi, puis l'a abandonné sans répondre : la page est
    revenue à une nouvelle discussion (vu avec 4 Argon Max. sur une longue demande Cowork)."""

    def __init__(self) -> None:
        super().__init__(
            "Gemini a abandonné ce message sans répondre (la page est revenue à une nouvelle discussion). "
            "Cela arrive avec un niveau de réflexion « Max. » sur une longue demande : "
            "choisis « Min. » ou « Moyen », puis renvoie ton message."
        )


class ChoixBloque(ErreurPilote):
    def __init__(self, nom: str, reinitialisation: str) -> None:
        self.nom = nom
        super().__init__(
            f"« {nom} » est bloqué : ton compte Gemini a atteint sa limite d'utilisation "
            f"(réinitialisation : {reinitialisation}). Choisis un autre modèle ou niveau, "
            "ou attends cette heure-là."
        )


class LimiteGemini(ErreurPilote):
    def __init__(self, bandeau: str) -> None:
        super().__init__(
            f"Ton compte Gemini a atteint sa limite d'utilisation (« {bandeau} »). "
            "Gemini n'accepte plus de message pour l'instant : choisis un modèle plus léger "
            "(par exemple Flash) ou attends l'heure indiquée."
        )


class DelaiDepasse(ErreurPilote):
    def __init__(self, delai: float, partiel: str) -> None:
        self.partiel = partiel
        message = f"Gemini n'a pas fini de répondre après {delai:.0f} s."
        if partiel:
            message += f" Début de la réponse :\n{partiel}"
        super().__init__(message)
