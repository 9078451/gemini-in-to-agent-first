import json

import httpx
import pytest

from fournisseurs.api_openai import PiloteOpenAI, trier_modeles
from fournisseurs.memoire import MemoireFils
from fournisseurs.reglages import ReglagesFournisseurs
from pilote.erreurs import (
    CleRefusee, DemandeRefusee, FournisseurIndisponible, Interrompu, LimiteFournisseur, ModeleIntrouvable,
)


def sse(*morceaux: str, fin: bool = True) -> bytes:
    lignes = [f"data: {json.dumps({'choices': [{'delta': {'content': m}}]})}\n\n" for m in morceaux]
    if fin:
        lignes.append("data: [DONE]\n\n")
    return "".join(lignes).encode()


class Serveur:
    """Faux fournisseur : chaque demande reçoit la réponse suivante de la liste."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.demandes: list[httpx.Request] = []

    def __call__(self, demande: httpx.Request) -> httpx.Response:
        self.demandes.append(demande)
        reponse = self.reponses.pop(0) if len(self.reponses) > 1 else self.reponses[0]
        return reponse() if callable(reponse) else reponse

    def corps(self, i=-1) -> dict:
        return json.loads(self.demandes[i].content)


@pytest.fixture
def reglages(tmp_path):
    r = ReglagesFournisseurs(tmp_path / "f.json")
    r.enregistrer("openai", actif=True, cle="sk-test-1234", modeles=["gpt-test"])
    r.enregistrer("ollama", actif=True)
    return r


def pilote(serveur, reglages, tmp_path, fournisseur="openai", attentes=(1.0, 3.0)):
    pauses = []
    p = PiloteOpenAI(fournisseur, reglages, MemoireFils(tmp_path / "fils.db"),
                     client=httpx.Client(transport=httpx.MockTransport(serveur)), attentes=attentes,
                     dormir=pauses.append)
    return p, pauses


def test_reponse_au_fil_et_conversation_gardee(reglages, tmp_path):
    serveur = Serveur(httpx.Response(200, content=sse("Bon", "jour", " !")))
    p, _ = pilote(serveur, reglages, tmp_path)
    vus = []
    r = p.envoyer(None, "Salut", au_fil=lambda texte, html: vus.append(texte))
    assert r.reponse == "Bonjour !" and r.modele == "gpt-test" and r.adresse.startswith("api:openai:")
    assert list(dict.fromkeys(vus)) == ["Bon", "Bonjour", "Bonjour !"]  # + vérifications entre les morceaux
    assert "<p>Bonjour !</p>" in r.html
    assert serveur.demandes[0].headers["authorization"] == "Bearer sk-test-1234"
    p.envoyer(r.adresse, "Et toi ?")
    assert [m["role"] for m in serveur.corps()["messages"]] == ["user", "assistant", "user"]
    assert serveur.corps()["messages"][1]["content"] == "Bonjour !"


def test_ollama_sans_cle(reglages, tmp_path):
    serveur = Serveur(httpx.Response(200, content=sse("ok")))
    p, _ = pilote(serveur, reglages, tmp_path, fournisseur="ollama")
    p.envoyer(None, "Salut", modele="llama3.2")
    assert "authorization" not in serveur.demandes[0].headers
    assert str(serveur.demandes[0].url) == "http://127.0.0.1:11434/v1/chat/completions"


def test_cle_absente_ou_refusee(reglages, tmp_path):
    reglages.enregistrer("openai", cle="")
    p, _ = pilote(Serveur(httpx.Response(200, content=sse("x"))), reglages, tmp_path)
    with pytest.raises(CleRefusee):
        p.envoyer(None, "Salut")
    reglages.enregistrer("openai", cle="fausse")
    p, _ = pilote(Serveur(httpx.Response(401, json={"error": {"message": "bad key"}})), reglages, tmp_path)
    with pytest.raises(CleRefusee):
        p.envoyer(None, "Salut")


def test_limite_reessayee_puis_reussie(reglages, tmp_path):
    serveur = Serveur(httpx.Response(429, json={"error": {"message": "slow down"}}),
                      httpx.Response(200, content=sse("ok")))
    p, pauses = pilote(serveur, reglages, tmp_path)
    assert p.envoyer(None, "Salut").reponse == "ok"
    assert pauses == [1.0]


def test_limite_qui_dure(reglages, tmp_path):
    serveur = Serveur(httpx.Response(429, json={"error": {"message": "quota"}}, headers={"retry-after": "2"}))
    p, pauses = pilote(serveur, reglages, tmp_path)
    with pytest.raises(LimiteFournisseur) as erreur:
        p.envoyer(None, "Salut")
    assert pauses == [2.0, 2.0] and len(serveur.demandes) == 3
    assert "quota" in str(erreur.value)


def test_retry_after_trop_long_pas_d_attente(reglages, tmp_path):
    serveur = Serveur(httpx.Response(429, json={"error": "quota"}, headers={"retry-after": "3600"}))
    p, pauses = pilote(serveur, reglages, tmp_path)
    with pytest.raises(LimiteFournisseur):
        p.envoyer(None, "Salut")
    assert pauses == [] and len(serveur.demandes) == 1


def test_panne_reessayee(reglages, tmp_path):
    serveur = Serveur(httpx.Response(503, text="overloaded"), httpx.Response(200, content=sse("ok")))
    p, _ = pilote(serveur, reglages, tmp_path)
    assert p.envoyer(None, "Salut").reponse == "ok"


def test_modele_introuvable(reglages, tmp_path):
    p, _ = pilote(Serveur(httpx.Response(404, json={"error": {"message": "no such model"}})), reglages, tmp_path)
    with pytest.raises(ModeleIntrouvable) as erreur:
        p.envoyer(None, "Salut", modele="gpt-inconnu")
    assert "OpenAI" in str(erreur.value)


def test_demande_refusee(reglages, tmp_path):
    p, _ = pilote(Serveur(httpx.Response(400, json={"error": {"message": "context too long"}})), reglages, tmp_path)
    with pytest.raises(DemandeRefusee) as erreur:
        p.envoyer(None, "Salut")
    assert "context too long" in str(erreur.value)


def test_niveau_refuse_par_le_modele_renvoye_sans(reglages, tmp_path):
    serveur = Serveur(httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'reasoning_effort'"}}),
                      httpx.Response(200, content=sse("ok")))
    p, _ = pilote(serveur, reglages, tmp_path)
    r = p.envoyer(None, "Salut", niveau="Max.")
    assert serveur.corps(0)["reasoning_effort"] == "high"
    assert "reasoning_effort" not in serveur.corps(1)
    assert r.niveau is None
    p.envoyer(None, "Encore", niveau="Max.")
    assert "reasoning_effort" not in serveur.corps()  # retenu pour ce modèle


class FluxCoupe(httpx.SyncByteStream):
    def __iter__(self):
        yield sse("Début", fin=False)
        raise httpx.RemoteProtocolError("peer closed connection")


def test_coupure_au_milieu_garde_le_debut_sans_nouvel_essai(reglages, tmp_path):
    serveur = Serveur(lambda: httpx.Response(200, stream=FluxCoupe()))
    p, _ = pilote(serveur, reglages, tmp_path)
    with pytest.raises(FournisseurIndisponible) as erreur:
        p.envoyer(None, "Salut")
    assert erreur.value.partiel == "Début"
    assert len(serveur.demandes) == 1


def test_arret_garde_le_partiel_dans_la_conversation(reglages, tmp_path):
    serveur = Serveur(httpx.Response(200, content=sse("Un", " deux", " trois")))
    p, _ = pilote(serveur, reglages, tmp_path)

    def au_fil(texte, html):
        if texte == "Un deux":
            raise Interrompu(texte, html)

    with pytest.raises(Interrompu) as erreur:
        p.envoyer(None, "Compte", au_fil=au_fil)
    assert erreur.value.partiel == "Un deux" and erreur.value.adresse.startswith("api:openai:")
    p.envoyer(erreur.value.adresse, "Continue")
    assert serveur.corps()["messages"][1] == {"role": "assistant", "content": "Un deux"}


def test_ollama_eteint(reglages, tmp_path):
    def refuse(demande):
        raise httpx.ConnectError("refused", request=demande)

    p, _ = pilote(refuse, reglages, tmp_path, fournisseur="ollama")
    with pytest.raises(FournisseurIndisponible) as erreur:
        p.envoyer(None, "Salut", modele="llama3.2")
    assert "Ollama est-il lancé" in str(erreur.value)


def test_erreur_dans_le_flux(reglages, tmp_path):
    corps = b'data: {"error": {"message": "provider overloaded", "code": 502}}\n\n'
    serveur = Serveur(httpx.Response(200, content=corps), httpx.Response(200, content=sse("ok")))
    p, _ = pilote(serveur, reglages, tmp_path)
    assert p.envoyer(None, "Salut").reponse == "ok"


def test_liste_des_modeles(reglages, tmp_path):
    donnees = {"data": [
        {"id": "gpt-ancien", "created": 1}, {"id": "text-embedding-3", "created": 9},
        {"id": "gpt-recent", "created": 5}, {"id": "models/gemini-x"}, {"id": "whisper-1", "created": 3},
    ]}
    p, _ = pilote(Serveur(httpx.Response(200, json=donnees)), reglages, tmp_path)
    assert p.lister_modeles() == ["gpt-recent", "gpt-ancien", "gemini-x"]
    assert trier_modeles([]) == []
