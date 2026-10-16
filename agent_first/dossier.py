"""Choisir un dossier de travail avec le sélecteur de dossier de Windows.

Le vrai sélecteur (tkinter) tourne dans un sous-processus : lancer Tk depuis un
fil du serveur est fragile. `ouvrir` est injectable pour les tests.
"""
import subprocess
import sys
from pathlib import Path
from typing import Callable

_CODE = (
    "import tkinter, tkinter.filedialog;"
    "r = tkinter.Tk(); r.withdraw(); r.attributes('-topmost', True);"
    "print(tkinter.filedialog.askdirectory() or '')"
)


def _tk_askdirectory() -> str | None:
    import os

    environ = dict(os.environ)
    base = Path(sys.base_prefix)
    tcl, tk = base / "tcl" / "tcl8.6", base / "tcl" / "tk8.6"
    if "TCL_LIBRARY" not in environ and tcl.is_dir() and tk.is_dir():
        environ["TCL_LIBRARY"], environ["TK_LIBRARY"] = str(tcl), str(tk)
    acheve = subprocess.run(
        [sys.executable, "-c", _CODE], capture_output=True, text=True, encoding="utf-8", env=environ, timeout=300
    )
    chemin = acheve.stdout.strip()
    return chemin or None


def choisir_dossier(ouvrir: Callable[[], str | None] = _tk_askdirectory) -> str | None:
    return ouvrir()
