"""Lance la fenêtre : python -m gui"""
import os
import sys
from pathlib import Path

import customtkinter as ctk

import config
from gui.app import Fenetre
from gui.client import ClientAgentFirst
from gui.correctif_tcl import corriger_tcl


def main() -> None:
    corriger_tcl(Path(sys.base_prefix), os.environ)
    ctk.set_appearance_mode("dark")
    client = ClientAgentFirst(f"http://{config.HOTE_AGENT}:{config.PORT_AGENT}", config.DELAI_GUI)
    Fenetre(client).mainloop()


if __name__ == "__main__":
    main()
