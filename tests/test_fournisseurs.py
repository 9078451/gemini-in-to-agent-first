import json
import threading
import time

import pytest

from fournisseurs.catalogue import CATALOGUE
from fournisseurs.etats import DECONNECTE, INCONNU, LIMITE, PANNE, PRET, EtatsFournisseurs
from fournisseurs.reglages import ReglagesFournisseurs, masquer
from fournisseurs.repartiteur import FileParallele, FournisseurInconnu, Repartiteur
from pilote.erreurs import (
    ChromeInjoignable, CleRefusee, Interrompu, LimiteGemini, ModeleIntrouvable, PasConnecteGoogle,
)

# ---- réglages -------------------------------------------------------------


def test_cle_jamais_rendue_en_clair(tmp_path):
    reglages = ReglagesFournisseurs(tmp_path / "f.json")
    reglages.enregistrer("anthropic", actif=True, cle="sk-ant-secret-1234")
    publics = {p["id"]: p for p in reglages.publics()}
    assert publics["anthropic"]["cle"] == "••••1234"
    assert "sk-ant-secret" not in json.dumps(reglages.publics())
    assert reglages.cle("anthropic") == "sk-ant-secret-1234"


def test_masquer_une_cle_courte():
    assert masquer("abc") == "••••"
    assert masquer(None) is None


def test_gemini_toujours_actif_les_autres_non(tmp_path):
    reglages = ReglagesFournisseurs(tmp_path / "f.json")
    assert reglages.actifs() == ["gemini"]
    reglages.enregistrer("ollama", actif=True)
    assert reglages.actifs() == ["gemini", "ollama"]


def test_garde_apres_redemarrage(tmp_path):
    fichier = tmp_path / "donnees" / "f.json"
    ReglagesFournisseurs(fichier).enregistrer("mistral", actif=True, cle="cle", modeles=["a", "a", " b "])
    relu = ReglagesFournisseurs(fichier)
    assert relu.config("mistral") == {"actif": True, "cle": "cle", "modeles": ["a", "b"], "url": None}


def test_fichier_abime_mis_de_cote(tmp_path):
    fichier = tmp_path / "f.json"
    fichier.write_text("{pas du json", encoding="utf-8")
    reglages = ReglagesFournisseurs(fichier)
    assert reglages.actifs() == ["gemini"]
    assert (tmp_path / "f.illisible.json").exists()


def test_url_perso_et_par_defaut(tmp_path):
    reglages = ReglagesFournisseurs(tmp_path / "f.json")
    assert reglages.url("ollama") == CATALOGUE["ollama"].base_url
    reglages.enregistrer("perso", url="http://192.168.1.5:1234/v1/")
    assert reglages.url("perso") == "http://192.168.1.5:1234/v1"


def test_secours(tmp_path):
    reglages = ReglagesFournisseurs(tmp_path / "f.json")
    assert reglages.secours() == {"actif": False, "fournisseur": None, "modele": None}
    reglages.regler_secours(True, "anthropic", "claude-haiku-5-5")
    assert ReglagesFournisseurs(tmp_path / "f.json").secours()["fournisseur"] == "anthropic"
    with pytest.raises(KeyError):
        reglages.regler_secours(True, "inconnu", None)


# ---- états ----------------------------------------------------------------


class Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_etats_depuis_les_erreurs():
    etats = EtatsFournisseurs()
    etats.noter_erreur("gemini", LimiteGemini("Votre limite sera réinitialisée à 2:58 PM"))
    etats.noter_erreur("anthropic", CleRefusee("Claude"))
    etats.noter_erreur("chatgpt", ChromeInjoignable())
    etats.noter_ok("ollama")
    assert etats.lire("gemini") == {"etat": LIMITE, "detail": "jusqu'à 2:58 PM"}
    assert etats.lire("anthropic")["etat"] == DECONNECTE
    assert etats.lire("chatgpt")["etat"] == PANNE
    assert etats.lire("ollama")["etat"] == PRET
    assert etats.lire("mistral")["etat"] == INCONNU


def test_erreur_sans_rapport_avec_le_fournisseur_ignoree():
    etats = EtatsFournisseurs()
    etats.noter_ok("gemini")
    etats.noter_erreur("gemini", ModeleIntrouvable("x"))
    etats.noter_erreur("gemini", Interrompu("début"))
    assert etats.lire("gemini")["etat"] == PRET


def test_limite_oubliee_apres_un_moment():
    horloge = Horloge()
    etats = EtatsFournisseurs(horloge)
    etats.noter_erreur("gemini", PasConnecteGoogle())
    etats.noter_erreur("chatgpt", LimiteGemini("plus tard"))
    horloge.t = 3600
    assert etats.lire("chatgpt")["etat"] == INCONNU
    assert etats.lire("gemini")["etat"] == DECONNECTE  # se reconnecter ne se fait pas tout seul


# ---- répartiteur ------------------------------------------------------------


class FauxPilote:
    def __init__(self, nom):
        self.nom = nom

    def envoyer(self, *args, **kwargs):
        return self.nom


def test_une_file_par_site_et_par_role_creee_une_fois():
    fabriques = {"gemini": lambda role: FauxPilote(f"gemini-{role}")}
    repartiteur = Repartiteur(fabriques, set())
    try:
        chat = repartiteur.file("gemini", "chat")
        assert repartiteur.file("gemini", "chat") is chat
        assert repartiteur.file("gemini", "cowork") is not chat
        assert chat.soumettre(lambda p: p.nom).result(timeout=2) == "gemini-chat"
    finally:
        repartiteur.arreter()


def test_une_seule_file_parallele_par_api():
    repartiteur = Repartiteur({"ollama": lambda role: FauxPilote("ollama")}, {"ollama"})
    try:
        assert repartiteur.file("ollama", "chat") is repartiteur.file("ollama", "cowork")
        assert isinstance(repartiteur.file("ollama", "chat"), FileParallele)
    finally:
        repartiteur.arreter()


def test_fournisseur_inconnu():
    with pytest.raises(FournisseurInconnu):
        Repartiteur({}, set()).file("chatgpt", "chat")


def test_file_parallele_fait_deux_demandes_en_meme_temps():
    file = FileParallele(lambda: FauxPilote("api"))
    ensemble = threading.Barrier(2, timeout=2)

    def travail(pilote):
        ensemble.wait()  # bloquerait si les deux demandes passaient l'une après l'autre
        return pilote.nom

    try:
        debut = time.monotonic()
        futurs = [file.soumettre(travail), file.soumettre(travail)]
        assert file.occupee()
        assert [f.result(timeout=3) for f in futurs] == ["api", "api"]
        assert time.monotonic() - debut < 2
        time.sleep(0.05)
        assert not file.occupee()
    finally:
        file.arreter()


def test_adresse_reglable_seulement_pour_un_serveur_local(tmp_path):
    reglages = ReglagesFournisseurs(tmp_path / "f.json")
    reglages.enregistrer("openai", url="http://mechant.example/v1")
    assert reglages.url("openai") == CATALOGUE["openai"].base_url
