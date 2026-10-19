"""Le pilote Claude avec le vrai SDK `anthropic`, branché sur un faux serveur (MockTransport)."""
import json

import anthropic
import httpx2
import pytest

from fournisseurs.api_anthropic import PiloteClaudeAPI
from fournisseurs.memoire import MemoireFils
from fournisseurs.reglages import ReglagesFournisseurs
from pilote.erreurs import CleRefusee, DemandeRefusee, Interrompu, LimiteFournisseur, ModeleIntrouvable


def evenement(nom: str, donnees: dict) -> str:
    return f"event: {nom}\ndata: {json.dumps(donnees)}\n\n"


def flux_claude(*morceaux: str, stop="end_turn", modele="claude-opus-5-5") -> bytes:
    sortie = [
        evenement("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": modele, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 1}}}),
        evenement("ping", {"type": "ping"}),
        evenement("content_block_start", {"type": "content_block_start", "index": 0,
                                          "content_block": {"type": "text", "text": ""}}),
    ]
    for m in morceaux:
        sortie.append(evenement("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                        "delta": {"type": "text_delta", "text": m}}))
    sortie += [
        evenement("content_block_stop", {"type": "content_block_stop", "index": 0}),
        evenement("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                    "usage": {"output_tokens": 5}}),
        evenement("message_stop", {"type": "message_stop"}),
    ]
    return "".join(sortie).encode()


class Serveur:
    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.demandes = []

    def __call__(self, demande):
        self.demandes.append(demande)
        return self.reponses.pop(0) if len(self.reponses) > 1 else self.reponses[0]

    def corps(self, i=-1):
        return json.loads(self.demandes[i].content)


def sse(contenu: bytes) -> httpx2.Response:
    return httpx2.Response(200, content=contenu, headers={"content-type": "text/event-stream"})


@pytest.fixture
def reglages(tmp_path):
    r = ReglagesFournisseurs(tmp_path / "f.json")
    r.enregistrer("anthropic", actif=True, cle="sk-ant-test")
    return r


def pilote(serveur, reglages, tmp_path):
    def fabrique(cle):
        return anthropic.Anthropic(api_key=cle, max_retries=0,
                                   http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(serveur)))
    return PiloteClaudeAPI(reglages, MemoireFils(tmp_path / "fils.db"), fabrique)


def test_reponse_en_flux(reglages, tmp_path):
    serveur = Serveur(sse(flux_claude("Bon", "jour")))
    vus = []
    r = pilote(serveur, reglages, tmp_path).envoyer(None, "Salut", niveau="Moyen",
                                                     au_fil=lambda texte, html: vus.append(texte))
    assert r.reponse == "Bonjour" and r.modele == "claude-opus-5-5" and r.niveau == "Moyen"
    assert "Bonjour" in vus
    corps = serveur.corps()
    assert corps["model"] == "claude-opus-5-5"  # le modèle par défaut
    assert corps["output_config"] == {"effort": "medium"}
    assert corps["fallbacks"] == "default" and corps["stream"] is True
    assert "server-side-fallback-2026-07-01" in serveur.demandes[0].headers["anthropic-beta"]
    assert serveur.demandes[0].headers["x-api-key"] == "sk-ant-test"


def test_conversation_continue(reglages, tmp_path):
    serveur = Serveur(sse(flux_claude("Salut !")))
    p = pilote(serveur, reglages, tmp_path)
    r = p.envoyer(None, "Bonjour", modele="claude-haiku-5-5")
    p.envoyer(r.adresse, "Ça va ?", modele="claude-haiku-5-5")
    assert serveur.corps()["messages"] == [
        {"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Salut !"},
        {"role": "user", "content": "Ça va ?"},
    ]


def test_sans_cle(tmp_path):
    p = pilote(Serveur(sse(flux_claude("x"))), ReglagesFournisseurs(tmp_path / "f.json"), tmp_path)
    with pytest.raises(CleRefusee):
        p.envoyer(None, "Salut")


@pytest.mark.parametrize("code, attendue", [(401, CleRefusee), (404, ModeleIntrouvable), (429, LimiteFournisseur),
                                            (400, DemandeRefusee)])
def test_erreurs_traduites(reglages, tmp_path, code, attendue):
    corps = {"type": "error", "error": {"type": "x", "message": "détail"}}
    p = pilote(Serveur(httpx2.Response(code, json=corps)), reglages, tmp_path)
    with pytest.raises(attendue):
        p.envoyer(None, "Salut")


def test_refus_sans_texte(reglages, tmp_path):
    p = pilote(Serveur(sse(flux_claude(stop="refusal"))), reglages, tmp_path)
    with pytest.raises(DemandeRefusee) as erreur:
        p.envoyer(None, "Salut")
    assert "sécurité" in str(erreur.value)


def test_arret(reglages, tmp_path):
    serveur = Serveur(sse(flux_claude("Un", " deux", " trois")))
    p = pilote(serveur, reglages, tmp_path)

    def au_fil(texte, html):
        if texte == "Un deux":
            raise Interrompu(texte, html)

    with pytest.raises(Interrompu) as erreur:
        p.envoyer(None, "Compte", au_fil=au_fil)
    assert erreur.value.partiel == "Un deux" and erreur.value.adresse.startswith("api:anthropic:")


def test_liste_des_modeles(reglages, tmp_path):
    donnees = {"data": [{"type": "model", "id": "claude-opus-5-5", "display_name": "Claude Opus 5.5",
                         "created_at": "2026-09-01T00:00:00Z"}], "has_more": False, "first_id": None, "last_id": None}
    p = pilote(Serveur(httpx2.Response(200, json=donnees)), reglages, tmp_path)
    assert p.lister_modeles() == ["claude-opus-5-5"]


def test_options_refusees_par_un_ancien_modele_renvoye_sans(reglages, tmp_path):
    refus = httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
                                                                  "message": "effort is not supported on this model"}})
    serveur = Serveur(refus, sse(flux_claude("ok")))
    r = pilote(serveur, reglages, tmp_path).envoyer(None, "Salut", modele="claude-ancien", niveau="Max.")
    assert r.reponse == "ok"
    assert "output_config" in serveur.corps(0) and "output_config" not in serveur.corps(1)
    assert "fallbacks" not in serveur.corps(1)
