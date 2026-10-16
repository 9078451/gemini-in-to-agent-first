from cowork.catalogue import liste_compacte
from cowork.format import PIED, Action, LigneResultat, est_erreur_gemini, formater_resultats, lire_actions, rappel_pour


def noms(message):
    return [a.nom for a in lire_actions(message)]


def test_un_bloc_une_action():
    assert lire_actions('```json\n{"action": "read", "path": "x.py"}\n```') == [Action("read", {"path": "x.py"})]


def test_plusieurs_blocs_dans_l_ordre():
    msg = (
        "Je vais lire les fichiers.\n"
        '```json\n{"action":"read","path":"a"}\n```\n'
        '```json\n{"action":"read","path":"b"}\n```'
    )
    assert [a.champs["path"] for a in lire_actions(msg)] == ["a", "b"]


def test_liste_dans_un_bloc():
    msg = '```json\n[{"action": "read", "path": "a"}, {"action": "list"}]\n```'
    assert noms(msg) == ["read", "list"]


def test_liste_affichee_par_gemini_web():
    # Gemini web affiche le bloc de code sans les ``` : « JSON » puis la liste, après « Gemini a dit ».
    msg = (
        'Gemini a dit\nJe commence.\nJSON\n[\n {"action": "plan", "steps": ["[ ] lire"]},\n'
        ' {"action": "list", "path": "."}\n]'
    )
    assert noms(msg) == ["plan", "list"]


def test_objet_affiche_sans_backticks():
    msg = 'Je crée le fichier.\nJSON\n{\n  "action": "creer",\n  "chemin": "a.txt",\n  "contenu": "x { y }"\n}'
    assert lire_actions(msg) == [Action("create", {"path": "a.txt", "content": "x { y }"})]


def test_plusieurs_objets_affiches_sans_backticks():
    msg = 'JSON\n{"action": "create", "path": "a", "content": "{ [ ] }"}\nJSON\n{"action": "read", "path": "a"}'
    assert noms(msg) == ["create", "read"]


def test_ignore_un_objet_sans_action():
    assert lire_actions('Voici un exemple : {"nom": "x"} et rien d\'autre.') == []


def test_rien_a_lire():
    assert lire_actions("je réfléchis") == []
    assert lire_actions("```json\n{action: lire}\n```") == []


def test_reparer_guillemets_non_echappes():
    # Vraie réponse de Gemini (Flash-Lite) : guillemets laissés tels quels dans les textes.
    msg = (
        'Gemini a dit\nJSON\n{"action": "modifier", "chemin": "server.py", '
        '"avant": "    with socketserver.TCPServer(("", PORT), httpd=MVCRequestHandler) as httpd:", '
        '"apres": "    with socketserver.TCPServer(("", PORT), MVCRequestHandler) as httpd:"}'
    )
    assert lire_actions(msg) == [Action("edit", {
        "path": "server.py",
        "old": '    with socketserver.TCPServer(("", PORT), httpd=MVCRequestHandler) as httpd:',
        "new": '    with socketserver.TCPServer(("", PORT), MVCRequestHandler) as httpd:',
    })]


def test_reparer_avec_cles_anglaises():
    msg = '{"action": "create", "path": "a.py", "content": "print("hi")"}'
    assert lire_actions(msg) == [Action("create", {"path": "a.py", "content": 'print("hi")'})]


def test_reparer_garde_les_echappements_valides():
    msg = '{"action": "creer", "chemin": "a.py", "contenu": "print("bonjour")\\nx = \\"1\\""}'
    assert lire_actions(msg) == [Action("create", {"path": "a.py", "content": 'print("bonjour")\nx = "1"'})]


def test_reparer_n_invente_pas_d_action():
    assert lire_actions('{"chemin": "a", "contenu": "x"y"}') == []
    assert lire_actions('{"action": "creer", "chemin": "a.py", "contenu": "x') == []


def test_termine_francais_vaut_done():
    assert lire_actions("TERMINÉ : fini") == [Action("done", {"summary": "fini"})]


def test_termine_dans_un_contenu_n_est_pas_une_fin():
    msg = '```json\n{"action": "create", "path": "a.txt", "content": "TERMINÉ"}\n```'
    assert noms(msg) == ["create"]


def test_formater_resultats():
    lignes = [
        LigneResultat(1, Action("create", {"path": "a.txt", "content": ""}), "OK", "a.txt created (1 line)"),
        LigneResultat(2, Action("run", {"command": "python x.py"}), "ERROR (exit code 1)", "boum"),
        LigneResultat(3, Action("create", {"path": "b.txt", "content": ""}), "SKIPPED", "an earlier action failed"),
    ]
    texte = formater_resultats(lignes, 8000, 30000)
    assert texte.startswith("RESULTS\n[1] create a.txt: OK\na.txt created (1 line)\n")
    assert '[2] run "python x.py": ERROR (exit code 1)\nboum' in texte
    assert "[3] create b.txt: SKIPPED" in texte
    assert texte.endswith(PIED)


def test_formater_resultats_avec_note():
    ligne = LigneResultat(1, Action("list", {}), "OK", "a")
    texte = formater_resultats([ligne], 8000, 30000, note="NOT FINISHED: x")
    assert "NOT FINISHED: x\n---\n" in texte


def test_resultat_coupe():
    ligne = LigneResultat(1, Action("read", {"path": "a"}), "OK", "x" * 50)
    assert "…(cut)" in formater_resultats([ligne], 10, 30000)


def test_message_entier_coupe():
    lignes = [LigneResultat(i, Action("read", {"path": "a"}), "OK", "x" * 100) for i in range(1, 6)]
    texte = formater_resultats(lignes, 8000, 300)
    assert len(texte) < 300 + len(PIED) + 50 and texte.endswith(PIED)


def test_rappel_json_abime():
    assert '\\"' in rappel_pour('{"action": "x", oups')


def test_rappel_general():
    assert liste_compacte() in rappel_pour("je réfléchis à voix haute")


def test_erreur_gemini():
    assert est_erreur_gemini("Gemini a dit\nSorry, something went wrong. Please try your request again.")
    assert est_erreur_gemini("")
    assert not est_erreur_gemini('```json\n{"action": "list"}\n```')


# --- JSON partiellement abîmé : ne jamais exécuter un lot amputé (relecture finale, critique #1) ---

def test_liste_avec_un_element_casse_garde_tout_le_lot_repare():
    msg = ('```json\n[{"action": "create", "path": "a.py", "content": "x = "a""}, '
           '{"action": "plan", "steps": ["[x] écrire a.py"]}, {"action": "done", "summary": "fait"}]\n```')
    actions = lire_actions(msg)
    assert [a.nom for a in actions] == ["create", "plan", "done"]  # jamais le plan et la fin sans la création
    assert actions[0].champs["content"] == 'x = "a"'


def test_liste_avec_un_element_irreparable_n_est_pas_lue():
    msg = ('```json\n[{"action": "create", "path": "a.py", "content": "x}, '
           '{"action": "plan", "steps": ["[x] écrire a.py"]}, {"action": "done", "summary": "fait"}]\n```')
    assert lire_actions(msg) == []


def test_deux_blocs_le_premier_repare():
    msg = ('```json\n{"action": "create", "path": "a.py", "content": "x = "a""}\n```\n'
           '```json\n{"action": "done", "summary": "fait"}\n```')
    assert lire_actions(msg) == [Action("create", {"path": "a.py", "content": 'x = "a"'}), Action("done", {"summary": "fait"})]


def test_deux_blocs_le_premier_irreparable():
    msg = ('```json\n[{"action": "create", "path": "a", "content": "x}, {"action": "read", "path": "b"}]\n```\n'
           '```json\n{"action": "done", "summary": "fait"}\n```')
    assert lire_actions(msg) == []


def test_objet_casse_ne_libere_pas_l_action_qu_il_contient():
    msg = 'JSON\n{"action": "create", "path": "x.md", "content": "Exemple : {"action": "delete", "path": "src"}"}'
    assert lire_actions(msg) == []


def test_creations_cassees_avec_termine_ne_finissent_pas():
    msg = ('JSON\n{"action": "create", "path": "a.md", "content": "TERMINÉ : "oui""}\n'
           'JSON\n{"action": "create", "path": "b.md", "content": "TERMINÉ "x""}')
    assert all(a.nom != "done" for a in lire_actions(msg))


def test_termine_dans_la_prose_n_est_pas_une_fin():
    assert lire_actions("Ce n'est pas encore TERMINÉ, je continue.") == []
