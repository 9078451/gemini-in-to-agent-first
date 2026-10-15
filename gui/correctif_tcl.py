"""Python 3.13.0 lancé depuis un venv ne trouve pas Tcl/Tk (corrigé en 3.13.1) :
on lui indique les dossiers de l'installation Python, avant de créer la fenêtre."""
from pathlib import Path
from typing import MutableMapping


def corriger_tcl(base_python: Path, environ: MutableMapping[str, str]) -> None:
    tcl, tk = base_python / "tcl" / "tcl8.6", base_python / "tcl" / "tk8.6"
    if "TCL_LIBRARY" in environ or not tcl.is_dir() or not tk.is_dir():
        return
    environ["TCL_LIBRARY"] = str(tcl)
    environ["TK_LIBRARY"] = str(tk)
