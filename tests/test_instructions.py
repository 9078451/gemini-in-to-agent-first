from pathlib import Path

from cowork.instructions import mode_emploi, premier_message


def test_mode_emploi_explique_l_echappement_json():
    # Sans cette règle, Gemini laissait des guillemets non échappés dans le code (JSON invalide).
    texte = mode_emploi(Path("C:/travail"))
    assert '\\"' in texte and "\\n" in texte


def test_premier_message_contient_dossier_et_tache():
    texte = premier_message(Path("C:/travail"), "crée a.txt")
    assert "C:" in texte and texte.endswith("Tâche : crée a.txt")
