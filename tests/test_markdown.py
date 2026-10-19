from agent_first.nettoyage import nettoyer_html
from fournisseurs.markdown import markdown_vers_html


def test_bloc_de_code_avec_sa_langue_garde_apres_nettoyage():
    html = nettoyer_html(markdown_vers_html("Voici :\n\n```python\nprint(1)\n```"))
    assert '<pre data-langue="python"><code>print(1)' in html


def test_tableau_et_html_brut_echappe():
    html = markdown_vers_html("| a | b |\n|---|---|\n| 1 | 2 |\n\n<script>x()</script>")
    assert "<table>" in html and "<script>" not in html
