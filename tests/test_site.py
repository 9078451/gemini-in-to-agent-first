from pilote.chrome import choisir_onglet
from pilote.site import limite_dans
from pilote.sites import CHATGPT, CLAUDE_WEB, PROFILS

REQUIS = ("champ_saisie", "bouton_envoyer", "question", "reponse", "generation")


def test_chaque_site_a_ses_reperes():
    for profil in PROFILS.values():
        for nom in REQUIS:
            assert profil.reperes.get(nom), (profil.id, nom)
        assert profil.url_nouvelle.startswith(profil.prefixe)


def test_modele_de_chatgpt_dans_l_adresse():
    assert CHATGPT.url_modele("gpt-5 mini") == "https://chatgpt.com/?model=gpt-5%20mini"
    assert CLAUDE_WEB.url_modele is None


def test_limite_trouvee_dans_la_page():
    page = "Bonjour\nYou've reached our limit of messages per hour. Please try again later.\nAutre chose"
    assert limite_dans(page, CHATGPT.textes_limite) == "You've reached our limit of messages per hour. Please try again later."
    assert limite_dans("Tout va bien", CHATGPT.textes_limite) is None


def test_onglet_choisi_sur_le_bon_site():
    onglets = [("https://gemini.google.com/app", "chat"), ("https://chatgpt.com/", None), ("https://chatgpt.com/c/1", "chat")]
    assert choisir_onglet(onglets, "chat", False, "https://chatgpt.com") == 2
    assert choisir_onglet(onglets, "chat", False) == 0  # Gemini par défaut
    assert choisir_onglet(onglets, "cowork", True, "https://chatgpt.com") == 1
    assert choisir_onglet(onglets, "cowork", False, "https://claude.ai") is None
