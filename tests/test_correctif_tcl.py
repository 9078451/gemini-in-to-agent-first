from gui.correctif_tcl import corriger_tcl


def installation(tmp_path):
    (tmp_path / "tcl" / "tcl8.6").mkdir(parents=True)
    (tmp_path / "tcl" / "tk8.6").mkdir(parents=True)
    return tmp_path


def test_indique_tcl_et_tk_de_l_installation_python(tmp_path):
    environ = {}
    corriger_tcl(installation(tmp_path), environ)
    assert environ == {
        "TCL_LIBRARY": str(tmp_path / "tcl" / "tcl8.6"),
        "TK_LIBRARY": str(tmp_path / "tcl" / "tk8.6"),
    }


def test_ne_touche_pas_un_reglage_existant(tmp_path):
    environ = {"TCL_LIBRARY": "ailleurs"}
    corriger_tcl(installation(tmp_path), environ)
    assert environ == {"TCL_LIBRARY": "ailleurs"}


def test_rien_si_tcl_absent(tmp_path):
    environ = {}
    corriger_tcl(tmp_path, environ)
    assert environ == {}
