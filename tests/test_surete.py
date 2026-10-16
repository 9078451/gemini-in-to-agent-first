from cowork.format import Action
from cowork.surete import classer


def cmd(texte: str) -> Action:
    return Action("run", {"command": texte})


def test_supprimer_dangereux():
    assert classer(Action("delete", {"path": "x"})).dangereuse is True


def test_creer_modifier_lire_surs():
    for nom in ("create", "edit", "read", "list", "search", "visit", "plan", "logs", "stop"):
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


def test_enchainement_non_sur_dangereux():
    for t in ("dir; Set-Content C:/x y", "dir | Out-File C:/x", "git status && rm x", "dir & copy a C:/b"):
        assert classer(cmd(t)).dangereuse is True, t


def test_enchainement_sur():
    for t in ("dir | findstr txt", "git status; git diff"):
        assert classer(cmd(t)).dangereuse is False, t


def test_redirection_dangereuse():
    assert classer(cmd("echo x > C:/Windows/a.txt")).dangereuse is True
    assert classer(cmd("type a.txt >> b.txt")).dangereuse is True


def test_redirection_des_erreurs_sure():
    assert classer(cmd("npm test 2>&1")).dangereuse is False


def test_git_destructif_dangereux():
    for t in ("git clean -fdx", "git reset --hard", "git checkout -- .", "pip uninstall requests -y"):
        assert classer(cmd(t)).dangereuse is True, t


def test_start_analyse_comme_run():
    assert classer(Action("start", {"command": "Remove-Item -Recurse x"})).dangereuse is True
    assert classer(Action("start", {"command": "python server.py"})).dangereuse is False
