"""Erreurs des pilotes (sites pilotés dans Chrome, API). Le texte de chaque erreur est
destiné à l'utilisateur.

`secours = True` : le fournisseur est à sa limite ou indisponible ; la demande peut
repartir chez le fournisseur de secours. Faux pour un choix de l'utilisateur à corriger
(modèle ou niveau introuvable) ou un arrêt demandé.
"""


class ErreurPilote(Exception):
    """Base de toutes les erreurs des pilotes."""

    secours = False


class Interrompu(ErreurPilote):
    """L'utilisateur a arrêté la réponse : `partiel` est ce qui était écrit, `adresse` la
    conversation chez le fournisseur (si le pilote la connaît)."""

    def __init__(self, partiel: str = "", html: str = "", adresse: str | None = None) -> None:
        self.partiel = partiel
        self.html = html
        self.adresse = adresse
        super().__init__("Réponse interrompue.")


class ChromeInjoignable(ErreurPilote):
    secours = True

    def __init__(self) -> None:
        super().__init__(
            "Impossible de joindre le Chrome dédié (port de débogage fermé). S'il est ouvert, "
            "ferme-le : Agent First le relancera au prochain message."
        )


class PasConnecteGoogle(ErreurPilote):
    secours = True

    def __init__(self) -> None:
        super().__init__(
            "Connecte-toi à Google dans la fenêtre Chrome dédiée, puis renvoie ton message."
        )


class VerificationGoogle(ErreurPilote):
    secours = True

    def __init__(self) -> None:
        super().__init__(
            "Google demande une vérification : fais-la toi-même dans la fenêtre "
            "Chrome dédiée, puis renvoie ton message."
        )


class RepereIntrouvable(ErreurPilote):
    secours = True

    def __init__(self, nom: str, capture: str | None = None, site: str = "Gemini") -> None:
        self.nom = nom
        self.capture = capture
        self.site = site
        message = f"Repère « {nom} » introuvable : {site} a peut-être changé son interface."
        if capture:
            message += f" Capture d'écran : {capture}"
        super().__init__(message)


class ModeleIntrouvable(ErreurPilote):
    def __init__(self, nom: str, fournisseur: str = "Gemini") -> None:
        self.nom = nom
        super().__init__(f"Le modèle « {nom} » n'est pas proposé par {fournisseur}.")


class NiveauIntrouvable(ErreurPilote):
    def __init__(self, nom: str) -> None:
        self.nom = nom
        super().__init__(f"Le niveau de réflexion « {nom} » n'est pas proposé par Gemini.")


class MessageNonEnvoye(ErreurPilote):
    secours = True

    def __init__(self) -> None:
        super().__init__(
            "Gemini n'a pas pris le message (connexion à Google coupée ?). "
            "Vérifie la fenêtre Chrome dédiée, puis renvoie ton message."
        )


class MessageAbandonne(ErreurPilote):
    """Gemini a pris le message, réfléchi, puis l'a abandonné sans répondre : la page est
    revenue à une nouvelle discussion (vu avec 4 Argon Max. sur une longue demande Cowork)."""

    secours = True

    def __init__(self) -> None:
        super().__init__(
            "Gemini a abandonné ce message sans répondre (la page est revenue à une nouvelle discussion). "
            "Cela arrive avec un niveau de réflexion « Max. » sur une longue demande : "
            "choisis « Min. » ou « Moyen », puis renvoie ton message."
        )


class ChoixBloque(ErreurPilote):
    secours = True

    def __init__(self, nom: str, reinitialisation: str) -> None:
        self.nom = nom
        super().__init__(
            f"« {nom} » est bloqué : ton compte Gemini a atteint sa limite d'utilisation "
            f"(réinitialisation : {reinitialisation}). Choisis un autre modèle ou niveau, "
            "ou attends cette heure-là."
        )


class LimiteGemini(ErreurPilote):
    secours = True

    def __init__(self, bandeau: str) -> None:
        super().__init__(
            f"Ton compte Gemini a atteint sa limite d'utilisation (« {bandeau} »). "
            "Gemini n'accepte plus de message pour l'instant : choisis un modèle plus léger "
            "(par exemple Flash) ou attends l'heure indiquée."
        )


class DelaiDepasse(ErreurPilote):
    secours = True

    def __init__(self, delai: float, partiel: str) -> None:
        self.partiel = partiel
        message = f"Gemini n'a pas fini de répondre après {delai:.0f} s."
        if partiel:
            message += f" Début de la réponse :\n{partiel}"
        super().__init__(message)


# ---- autres fournisseurs ---------------------------------------------------


class PasConnecteSite(ErreurPilote):
    secours = True

    def __init__(self, site: str) -> None:
        super().__init__(
            f"Connecte-toi à {site} dans la fenêtre Chrome dédiée (Paramètres → Fournisseurs → "
            "Ouvrir), puis renvoie ton message."
        )


class LimiteSite(ErreurPilote):
    secours = True

    def __init__(self, site: str, texte: str) -> None:
        super().__init__(f"{site} refuse le message pour l'instant (« {texte} »).")


class CleRefusee(ErreurPilote):
    secours = True

    def __init__(self, fournisseur: str) -> None:
        super().__init__(
            f"{fournisseur} refuse la clé API (absente, fausse ou sans accès à ce modèle). "
            "Vérifie-la dans Paramètres → Fournisseurs."
        )


class LimiteFournisseur(ErreurPilote):
    secours = True

    def __init__(self, fournisseur: str, detail: str = "") -> None:
        message = f"{fournisseur} limite les demandes pour l'instant (quota ou débit atteint)."
        if detail:
            message += f" Détail : {detail}"
        super().__init__(message)


class FournisseurIndisponible(ErreurPilote):
    secours = True

    def __init__(self, fournisseur: str, detail: str = "", partiel: str = "") -> None:
        self.partiel = partiel
        message = f"{fournisseur} ne répond pas correctement"
        message += f" : {detail}" if detail else "."
        if partiel:
            message += f"\nDébut de la réponse :\n{partiel}"
        super().__init__(message)


class DemandeRefusee(ErreurPilote):
    """Le fournisseur refuse la demande elle-même (contenu, taille, paramètre)."""

    def __init__(self, fournisseur: str, detail: str) -> None:
        super().__init__(f"{fournisseur} refuse la demande : {detail}")
