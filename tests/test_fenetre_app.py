from pathlib import Path

from agent_first.fenetre import commande_fenetre, ouvrir_quand_pret

CHROME = Path("C:/chrome.exe")


def test_commande_fenetre_mode_application():
    assert commande_fenetre(CHROME, "http://127.0.0.1:8765/") == [
        str(CHROME), "--app=http://127.0.0.1:8765/", "--window-size=1280,820",
    ]


def test_ouvre_des_que_le_serveur_repond():
    reponses = iter([False, False, True])
    lancees = []
    assert ouvrir_quand_pret(CHROME, "http://x/", lambda: next(reponses), lancer=lancees.append, intervalle=0) is True
    assert lancees == [commande_fenetre(CHROME, "http://x/")]


def test_abandonne_si_le_serveur_ne_repond_pas():
    lancees = []
    assert ouvrir_quand_pret(CHROME, "http://x/", lambda: False, lancer=lancees.append, delai=0.05, intervalle=0.01) is False
    assert lancees == []
