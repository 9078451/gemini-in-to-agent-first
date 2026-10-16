from cowork.format import Action, est_termine, formater_resultat, lire_action


def test_lire_action_bloc_valide():
    a = lire_action('```json\n{"action": "lire", "chemin": "x.py"}\n```')
    assert a == Action("lire", {"chemin": "x.py"})


def test_lire_action_ignore_le_texte_autour():
    msg = (
        "Je vais lire le fichier.\n"
        '```json\n{"action":"lire","chemin":"a"}\n```\n'
        '```json\n{"action":"lire","chemin":"b"}\n```'
    )
    assert lire_action(msg) == Action("lire", {"chemin": "a"})


def test_lire_action_json_casse():
    assert lire_action("```json\n{action: lire}\n```") is None


def test_lire_action_sans_cle_action():
    assert lire_action('```json\n{"chemin": "x"}\n```') is None


def test_lire_action_aucun_bloc():
    assert lire_action("TERMINÉ : voilà, c'est fait.") is None


def test_est_termine():
    assert est_termine("TERMINÉ : fini") is True
    assert est_termine('```json\n{"action":"lire","chemin":"x"}\n```') is False
    assert est_termine("je réfléchis encore") is False


def test_formater_resultat():
    assert formater_resultat(True, "deux fichiers") == "OK\ndeux fichiers"
    assert formater_resultat(False, "fichier absent") == "ERREUR : fichier absent"


def test_lire_action_dans_le_texte_affiche_par_gemini():
    # Gemini web affiche le bloc de code sans les ``` : « JSON » puis l'objet.
    msg = 'Je crée le fichier.\nJSON\n{\n  "action": "creer",\n  "chemin": "a.txt",\n  "contenu": "x { y }"\n}'
    assert lire_action(msg) == Action("creer", {"chemin": "a.txt", "contenu": "x { y }"})


def test_lire_action_ignore_un_objet_sans_action():
    assert lire_action('Voici un exemple : {"nom": "x"} et rien d\'autre.') is None


def test_reparer_guillemets_non_echappes():
    # Vraie réponse de Gemini (Flash-Lite) : guillemets laissés tels quels dans les textes.
    msg = (
        'Gemini a dit\nJSON\n{"action": "modifier", "chemin": "server.py", '
        '"avant": "    with socketserver.TCPServer(("", PORT), httpd=MVCRequestHandler) as httpd:", '
        '"apres": "    with socketserver.TCPServer(("", PORT), MVCRequestHandler) as httpd:"}'
    )
    assert lire_action(msg) == Action("modifier", {
        "chemin": "server.py",
        "avant": '    with socketserver.TCPServer(("", PORT), httpd=MVCRequestHandler) as httpd:',
        "apres": '    with socketserver.TCPServer(("", PORT), MVCRequestHandler) as httpd:',
    })


def test_reparer_garde_les_echappements_valides():
    msg = '{"action": "creer", "chemin": "a.py", "contenu": "print("bonjour")\\nx = \\"1\\""}'
    assert lire_action(msg) == Action("creer", {"chemin": "a.py", "contenu": 'print("bonjour")\nx = "1"'})


def test_reparer_n_invente_pas_d_action():
    assert lire_action('{"chemin": "a", "contenu": "x"y"}') is None
    assert lire_action('{"action": "creer", "chemin": "a.py", "contenu": "x') is None
