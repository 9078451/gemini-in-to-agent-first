import re

import config
from cowork.catalogue import ANCIENS_NOMS, CATALOGUE

GERES_PAR_AGENT_FIRST = {"plan", "ask", "done"}  # pas des lignes d'étape : ils ont leur propre carte


def _cles(bloc_nom: str) -> set[str]:
    texte = (config.DOSSIER_WEB / "outils_cowork.js").read_text(encoding="utf-8")
    bloc = re.search(r"const %s = \{(.*?)\n\};" % bloc_nom, texte, re.S).group(1)
    return set(re.findall(r"^\s*(\w+):", bloc, re.M))


def test_chaque_action_a_son_libelle_dans_l_app():
    assert set(CATALOGUE) - GERES_PAR_AGENT_FIRST <= _cles("ACTIONS")


def test_chaque_ancien_nom_est_traduit_dans_l_app():
    assert set(ANCIENS_NOMS) <= _cles("ANCIENS")
