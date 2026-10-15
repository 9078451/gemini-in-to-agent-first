"""Couleurs et polices de la fenêtre : thème sombre, accent vert."""
import customtkinter as ctk

FOND = "#0d0d0f"
BARRE = "#111114"
CARTE = "#17171a"
CARTE_INTERNE = "#1e1e22"
SURVOL = "#26262b"
BORDURE = "#26262b"
TEXTE = "#f4f4f5"
TEXTE_2 = "#a1a1aa"
TEXTE_3 = "#6b6b75"
VERT = "#2fd99b"
ORANGE = "#f5b14c"
ROUGE = "#f06363"

POLICE = "Segoe UI"
POLICE_LOGO = "Consolas"


def police(taille: int, gras: bool = False, famille: str = POLICE) -> ctk.CTkFont:
    """À appeler après la création de la fenêtre (Tk doit exister)."""
    return ctk.CTkFont(family=famille, size=taille, weight="bold" if gras else "normal")
