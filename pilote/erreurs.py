"""Erreurs du pilote. Le texte de chaque erreur est destiné à l'utilisateur."""


class ErreurPilote(Exception):
    """Base de toutes les erreurs du pilote navigateur."""


class ChromeInjoignable(ErreurPilote):
    def __init__(self) -> None:
        super().__init__("Impossible de joindre le Chrome dédié (port de débogage fermé).")


class PasConnecteGoogle(ErreurPilote):
    """Le compte du site (Google pour Gemini, OpenAI pour ChatGPT…) n'est pas connecté."""

    def __init__(self, compte: str = "Google") -> None:
        self.compte = compte
        super().__init__(
            f"Connecte-toi à {compte} dans la fenêtre Chrome dédiée, puis renvoie ton message."
        )


class VerificationGoogle(ErreurPilote):
    def __init__(self, compte: str = "Google") -> None:
        super().__init__(
            f"{compte} demande une vérification : fais-la toi-même dans la fenêtre "
            "Chrome dédiée, puis renvoie ton message."
        )


PasConnecte = PasConnecteGoogle
VerificationRequise = VerificationGoogle


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


class LimiteAtteinte(ErreurPilote):
    """Le site est saturé, ou le compte n'a plus de messages ou de crédits pour l'instant."""

    def __init__(self, site: str, detail: str) -> None:
        self.site = site
        self.detail = detail
        super().__init__(
            f"{site} est saturé ou ton compte a atteint sa limite (« {detail} »). "
            "Choisis un autre modèle, ou active la redondance pour passer automatiquement au suivant."
        )


class LimiteGemini(LimiteAtteinte):
    def __init__(self, bandeau: str) -> None:
        self.site, self.detail = "Gemini", bandeau
        ErreurPilote.__init__(
            self,
            f"Ton compte Gemini a atteint sa limite d'utilisation (« {bandeau} »). "
            "Gemini n'accepte plus de message pour l'instant : choisis un modèle plus léger "
            "(par exemple Flash) ou attends l'heure indiquée."
        )


class PieceRefusee(ErreurPilote):
    def __init__(self, nom: str) -> None:
        self.nom = nom
        super().__init__(
            f"Gemini n'a pas accepté la pièce jointe « {nom} » (collée, déposée puis choisie avec « + »). "
            "Vérifie qu'il accepte ce type de fichier, ou joins-le toi-même dans la fenêtre Chrome dédiée."
        )


class PageInstable(ErreurPilote):
    """La page de Gemini a changé sous le pilote (onglet fermé ou rechargé, Chrome relancé)."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            "La page Gemini a changé pendant l'envoi (onglet fermé ou rechargé ?). "
            f"Vérifie la fenêtre Chrome dédiée, puis renvoie ton message. Détail : {detail}"
        )


class DelaiDepasse(ErreurPilote):
    def __init__(self, delai: float, partiel: str) -> None:
        self.partiel = partiel
        message = f"Gemini n'a pas fini de répondre après {delai:.0f} s."
        if partiel:
            message += f" Début de la réponse :\n{partiel}"
        super().__init__(message)
