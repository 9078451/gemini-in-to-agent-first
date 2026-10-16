from cowork.format import Action
from cowork.surete import classer


def cmd(texte: str) -> Action:
    return Action("commande", {"texte": texte})


def test_supprimer_dangereux():
    assert classer(Action("supprimer", {"chemin": "x"})).dangereuse is True


def test_creer_modifier_lire_surs():
    for nom in ("creer", "modifier", "lire", "lister", "chercher"):
        assert classer(Action(nom, {})).dangereuse is False


def test_commandes_sures():
    for t in ("dir", "python script.py", "npm test", "git status", "git diff"):
        assert classer(cmd(t)).dangereuse is False


def test_commandes_dangereuses():
    for t in (
        "Remove-Item -Recurse -Force x",
        "git push",
        "pip install requests",
        "Stop-Computer",
        "reg add HKLM\\...",
        "icacls x /grant",
        "Format-Volume",
    ):
        assert classer(cmd(t)).dangereuse is True


def test_commande_inconnue_dangereuse():
    assert classer(cmd("bidouille-inconnue --go")).dangereuse is True


def test_raison_presente():
    assert classer(cmd("git push")).raison != ""
