"""Fenêtre de discussion avec Gemini, via Agent First (thème sombre)."""
import queue
import threading
from typing import Any, Callable

import customtkinter as ctk

from gui import theme as t
from gui.client import ClientAgentFirst, ErreurClient


def taille_fenetre(ecran_largeur: int, ecran_hauteur: int, echelle: float) -> tuple[int, int]:
    """Taille de la fenêtre (unités CustomTkinter) : 1100×720 au plus, sans
    déborder de l'écran une fois la mise à l'échelle de Windows appliquée."""
    largeur = min(1100, int(ecran_largeur * 0.9 / echelle))
    hauteur = min(720, int(ecran_hauteur * 0.85 / echelle))
    return largeur, hauteur


def titre_conversation(texte: str, longueur: int = 28) -> str:
    """Premier message résumé sur une seule ligne, pour la barre latérale."""
    titre = " ".join(texte.split())
    return titre if len(titre) <= longueur else titre[: longueur - 1] + "…"


class Fenetre(ctk.CTk):
    def __init__(self, client: ClientAgentFirst) -> None:
        super().__init__(fg_color=t.FOND)
        self._client = client
        self._conversation: str | None = None
        self._occupe = False
        self._resultats: queue.Queue = queue.Queue()

        self.title("agent.first · Gemini")
        largeur, hauteur = taille_fenetre(
            self.winfo_screenwidth(), self.winfo_screenheight(), ctk.ScalingTracker.get_window_scaling(self)
        )
        self.geometry(f"{largeur}x{hauteur}")
        self.minsize(760, 500)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._construire_barre()
        self._construire_principal()

        self.after(100, self._relever_resultats)
        self.after(200, self._verifier_etat)

    # ---- construction ---------------------------------------------------

    def _construire_barre(self) -> None:
        barre = ctk.CTkFrame(self, width=260, fg_color=t.BARRE, corner_radius=0)
        barre.grid(row=0, column=0, sticky="nsw")
        barre.grid_propagate(False)
        barre.grid_columnconfigure(0, weight=1)

        logo = ctk.CTkFrame(barre, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="w", padx=24, pady=(28, 24))
        for morceau, couleur in (("agent", t.TEXTE), (".", t.VERT), ("first", t.TEXTE)):
            ctk.CTkLabel(
                logo, text=morceau, text_color=couleur, font=t.police(20, gras=True, famille=t.POLICE_LOGO)
            ).pack(side="left", padx=0)

        ctk.CTkButton(
            barre,
            text="+   Nouvelle conversation",
            command=self._nouvelle_conversation,
            fg_color=t.CARTE_INTERNE,
            hover_color=t.SURVOL,
            text_color=t.TEXTE,
            font=t.police(14, gras=True),
            corner_radius=12,
            height=44,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=16)

        self._titre_section(barre, "CONVERSATION").grid(row=2, column=0, sticky="w", padx=24, pady=(30, 8))
        self._libelle_conversation = ctk.CTkLabel(
            barre, text="Aucune conversation", text_color=t.TEXTE_2, font=t.police(13), anchor="w"
        )
        self._libelle_conversation.grid(row=3, column=0, sticky="ew", padx=24)

        self._titre_section(barre, "ÉTAT").grid(row=4, column=0, sticky="w", padx=24, pady=(30, 8))
        etats = ctk.CTkFrame(barre, fg_color="transparent")
        etats.grid(row=5, column=0, sticky="ew", padx=24)
        self._etat_agent = self._ligne_etat(etats)
        self._etat_chrome = self._ligne_etat(etats)
        self._etat_google = self._ligne_etat(etats)
        self._mettre_etat(self._etat_agent, "Agent First · connexion…", t.TEXTE_3)
        self._mettre_etat(self._etat_chrome, "Chrome dédié · …", t.TEXTE_3)
        self._mettre_etat(self._etat_google, "Compte Google · …", t.TEXTE_3)

    def _construire_principal(self) -> None:
        principal = ctk.CTkFrame(self, fg_color="transparent")
        principal.grid(row=0, column=1, sticky="nsew", padx=32, pady=(30, 24))
        principal.grid_columnconfigure(0, weight=1)
        principal.grid_rowconfigure(1, weight=1)

        entete = ctk.CTkFrame(principal, fg_color="transparent")
        entete.grid(row=0, column=0, pady=(0, 22))
        titre = ctk.CTkFrame(entete, fg_color="transparent")
        titre.pack()
        ctk.CTkLabel(titre, text="Discute avec ", text_color=t.TEXTE, font=t.police(28, gras=True)).pack(side="left")
        ctk.CTkLabel(titre, text="Gemini", text_color=t.VERT, font=t.police(28, gras=True)).pack(side="left")
        ctk.CTkLabel(
            entete,
            text="Tes messages passent par Agent First et le Chrome dédié.",
            text_color=t.TEXTE_2,
            font=t.police(15),
        ).pack(pady=(4, 0))

        carte = ctk.CTkFrame(principal, fg_color=t.CARTE, corner_radius=20, border_width=1, border_color=t.BORDURE)
        carte.grid(row=1, column=0, sticky="nsew")
        carte.grid_columnconfigure(0, weight=1)
        carte.grid_rowconfigure(0, weight=1)
        self._historique = ctk.CTkTextbox(
            carte,
            fg_color=t.CARTE,
            text_color=t.TEXTE,
            font=t.police(14),
            wrap="word",
            state="disabled",
            scrollbar_button_color=t.BORDURE,
            scrollbar_button_hover_color=t.SURVOL,
        )
        self._historique.grid(row=0, column=0, sticky="nsew", padx=18, pady=16)
        self._historique.tag_config("toi", foreground=t.VERT, spacing1=12)
        self._historique.tag_config("gemini", foreground=t.TEXTE_2, spacing1=12)
        self._historique.tag_config("erreur", foreground=t.ROUGE, spacing1=12)
        self._historique.tag_config("message", spacing3=6)

        saisie = ctk.CTkFrame(principal, fg_color=t.CARTE, corner_radius=28, border_width=1, border_color=t.BORDURE)
        saisie.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        saisie.grid_columnconfigure(0, weight=1)
        self._saisie = ctk.CTkTextbox(
            saisie,
            height=52,
            fg_color=t.CARTE,
            text_color=t.TEXTE,
            font=t.police(15),
            wrap="word",
            activate_scrollbars=False,
        )
        self._saisie.grid(row=0, column=0, sticky="ew", padx=(22, 8), pady=8)
        # Entrée envoie ; Maj+Entrée va à la ligne (comportement par défaut du champ).
        self._saisie.bind("<Return>", self._sur_entree)
        self._saisie.bind("<Shift-Return>", lambda _e: None)
        self._bouton_envoyer = ctk.CTkButton(
            saisie,
            text="→",
            command=self._envoyer,
            width=44,
            height=44,
            corner_radius=22,
            fg_color=t.CARTE_INTERNE,
            hover_color=t.SURVOL,
            text_color=t.TEXTE,
            font=t.police(18, gras=True),
        )
        self._bouton_envoyer.grid(row=0, column=1, padx=(0, 8), pady=8)

        pied = ctk.CTkFrame(principal, fg_color="transparent")
        pied.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        pied.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            pied,
            text="Entrée pour envoyer · Maj+Entrée pour aller à la ligne",
            text_color=t.TEXTE_3,
            font=t.police(12),
        ).grid(row=0, column=0, sticky="w", padx=10)
        pastille = ctk.CTkFrame(pied, fg_color=t.TEXTE, corner_radius=18)
        pastille.grid(row=0, column=1, sticky="e")
        self._texte_pastille = ctk.CTkLabel(
            pastille, text="Connexion…", text_color=t.FOND, font=t.police(13, gras=True)
        )
        self._texte_pastille.pack(side="left", padx=(16, 8), pady=6)
        self._point_pastille = ctk.CTkFrame(pastille, width=8, height=8, corner_radius=4, fg_color=t.TEXTE_3)
        self._point_pastille.pack(side="left", padx=(0, 16))

    def _titre_section(self, parent: ctk.CTkFrame, texte: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=texte, text_color=t.TEXTE_3, font=t.police(12, gras=True))

    def _ligne_etat(self, parent: ctk.CTkFrame) -> tuple[ctk.CTkFrame, ctk.CTkLabel]:
        ligne = ctk.CTkFrame(parent, fg_color="transparent")
        ligne.pack(fill="x", pady=5)
        point = ctk.CTkFrame(ligne, width=8, height=8, corner_radius=4, fg_color=t.TEXTE_3)
        point.pack(side="left", padx=(0, 10))
        etiquette = ctk.CTkLabel(ligne, text="", text_color=t.TEXTE_2, font=t.police(13), anchor="w")
        etiquette.pack(side="left", fill="x", expand=True)
        return point, etiquette

    # ---- actions --------------------------------------------------------

    def _sur_entree(self, _evenement) -> str:
        self._envoyer()
        return "break"

    def _envoyer(self) -> None:
        texte = self._saisie.get("1.0", "end").strip()
        if not texte or self._occupe:
            return
        self._saisie.delete("1.0", "end")
        if self._conversation is None:
            self._libelle_conversation.configure(text=titre_conversation(texte))
        self._ajouter("Toi", texte, "toi")
        self._occuper(True)
        conversation = self._conversation

        def travail() -> tuple[str, str]:
            identifiant = conversation or self._client.nouvelle_conversation()
            return identifiant, self._client.envoyer(identifiant, texte)

        def quand_fini(resultat: tuple[str, str] | None, erreur: str | None) -> None:
            self._occuper(False)
            if erreur:
                self._ajouter("Erreur", erreur, "erreur")
                self._signaler("Erreur", t.ROUGE)
                self._saisie.insert("1.0", texte)  # pour pouvoir le renvoyer
                return
            self._conversation, reponse = resultat
            self._ajouter("Gemini", reponse, "gemini")
            self._mettre_etat(self._etat_chrome, "Chrome dédié · ouvert", t.VERT)
            self._mettre_etat(self._etat_google, "Compte Google · connecté", t.VERT)

        self._lancer(travail, quand_fini)

    def _nouvelle_conversation(self) -> None:
        if self._occupe:
            return
        self._conversation = None
        self._libelle_conversation.configure(text="Nouvelle conversation")
        self._historique.configure(state="normal")
        self._historique.delete("1.0", "end")
        self._historique.configure(state="disabled")
        self._saisie.focus_set()

    def _verifier_etat(self) -> None:
        def quand_fini(etat: dict | None, erreur: str | None) -> None:
            if erreur:
                self._mettre_etat(self._etat_agent, "Agent First · pas démarré", t.ROUGE)
                self._signaler("Agent First arrêté", t.ROUGE)
                self.after(3000, self._verifier_etat)
                return
            self._mettre_etat(self._etat_agent, "Agent First · prêt", t.VERT)
            if etat["chrome"]:
                self._mettre_etat(self._etat_chrome, "Chrome dédié · ouvert", t.VERT)
            else:
                self._mettre_etat(self._etat_chrome, "Chrome dédié · au 1er message", t.TEXTE_3)
            google = {
                True: ("connecté", t.VERT),
                False: ("non connecté", t.ROUGE),
                None: ("à vérifier", t.TEXTE_3),
            }[etat["google"]]
            self._mettre_etat(self._etat_google, f"Compte Google · {google[0]}", google[1])
            if not self._occupe:
                self._signaler("Prêt", t.VERT)

        self._lancer(self._client.etat, quand_fini)

    # ---- outils ---------------------------------------------------------

    def _lancer(self, travail: Callable[[], Any], quand_fini: Callable[[Any, str | None], None]) -> None:
        """Exécute `travail` hors du fil de la fenêtre ; `quand_fini(resultat, erreur)`
        est ensuite appelé dans le fil de la fenêtre."""

        def fil() -> None:
            try:
                self._resultats.put((quand_fini, travail(), None))
            except ErreurClient as e:
                self._resultats.put((quand_fini, None, str(e)))

        threading.Thread(target=fil, daemon=True).start()

    def _relever_resultats(self) -> None:
        while True:
            try:
                quand_fini, resultat, erreur = self._resultats.get_nowait()
            except queue.Empty:
                break
            quand_fini(resultat, erreur)
        self.after(100, self._relever_resultats)

    def _occuper(self, occupe: bool) -> None:
        self._occupe = occupe
        self._bouton_envoyer.configure(state="disabled" if occupe else "normal")
        if occupe:
            self._signaler("Gemini écrit…", t.ORANGE)
        else:
            self._signaler("Prêt", t.VERT)

    def _signaler(self, texte: str, couleur: str) -> None:
        self._texte_pastille.configure(text=texte)
        self._point_pastille.configure(fg_color=couleur)

    def _mettre_etat(self, ligne: tuple[ctk.CTkFrame, ctk.CTkLabel], texte: str, couleur: str) -> None:
        point, etiquette = ligne
        point.configure(fg_color=couleur)
        etiquette.configure(text=texte)

    def _ajouter(self, auteur: str, texte: str, tag: str) -> None:
        self._historique.configure(state="normal")
        self._historique.insert("end", f"{auteur}\n", tag)
        self._historique.insert("end", f"{texte}\n", "message")
        self._historique.configure(state="disabled")
        self._historique.see("end")
