from cowork.catalogue import CATALOGUE, liste_compacte, normaliser, resume_action, valider
from cowork.format import Action


def test_alias_francais_normalises():
    assert normaliser({"action": "creer", "chemin": "a", "contenu": "x"}) == Action("create", {"path": "a", "content": "x"})


def test_tous_les_anciens_noms():
    anciens = {"lister": "list", "lire": "read", "chercher": "search", "creer": "create",
               "modifier": "edit", "supprimer": "delete", "commande": "run"}
    for ancien, nouveau in anciens.items():
        assert normaliser({"action": ancien}).nom == nouveau


def test_anciens_champs():
    action = normaliser({"action": "modifier", "chemin": "a", "avant": "x", "apres": "y"})
    assert action.champs == {"path": "a", "old": "x", "new": "y"}
    assert normaliser({"action": "commande", "texte": "dir"}).champs == {"command": "dir"}
    assert normaliser({"action": "chercher", "motif": "def"}).champs == {"pattern": "def"}


def test_steps_reste_une_liste():
    assert normaliser({"action": "plan", "steps": ["[ ] a"]}).champs["steps"] == ["[ ] a"]


def test_nombre_devient_texte():
    assert normaliser({"action": "stop", "id": 1}).champs["id"] == "1"


def test_sans_cle_action():
    assert normaliser({"path": "a"}) is None
    assert normaliser({"action": 3}) is None


def test_valider_champ_manquant():
    assert valider(Action("read", {})) == 'missing field "path"'
    assert valider(Action("list", {})) is None
    assert valider(Action("create", {"path": "a"})) == 'missing field "content"'


def test_valider_action_inconnue():
    message = valider(Action("fly", {}))
    assert message.startswith('unknown action "fly"') and "create" in message


def test_resume_action():
    assert resume_action(Action("run", {"command": "dir"})) == 'run "dir"'
    assert resume_action(Action("create", {"path": "index.html", "content": "x"})) == "create index.html"
    assert resume_action(Action("visit", {"url": "http://localhost:8080/"})) == "visit http://localhost:8080/"
    assert resume_action(Action("stop", {"id": "1"})) == "stop #1"
    assert resume_action(Action("plan", {"steps": []})) == "plan"


def test_liste_compacte_couvre_tout_le_catalogue():
    texte = liste_compacte()
    for nom in CATALOGUE:
        assert f'"action": "{nom}"' in texte
