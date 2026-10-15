import json

import httpx
import pytest

from gui.client import ClientAgentFirst, ErreurClient


def client_avec(gestionnaire) -> ClientAgentFirst:
    return ClientAgentFirst("http://agent", 300.0, transport=httpx.MockTransport(gestionnaire))


def test_envoyer_renvoie_la_reponse():
    recu = {}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        recu["chemin"] = requete.url.path
        recu["corps"] = json.loads(requete.content)
        return httpx.Response(200, json={"conversation": "c1", "reponse": "Salut !"})

    assert client_avec(gestionnaire).envoyer("c1", "Bonjour") == "Salut !"
    assert recu == {"chemin": "/message", "corps": {"conversation": "c1", "texte": "Bonjour"}}


def test_nouvelle_conversation():
    client = client_avec(lambda r: httpx.Response(200, json={"conversation": "c42"}))
    assert client.nouvelle_conversation() == "c42"


def test_erreur_d_agent_first_affichee_telle_quelle():
    client = client_avec(lambda r: httpx.Response(502, json={"erreur": "Connecte-toi à Google."}))
    with pytest.raises(ErreurClient, match="Connecte-toi à Google."):
        client.envoyer("c1", "Bonjour")


def test_agent_first_pas_demarre():
    def gestionnaire(requete):
        raise httpx.ConnectError("refusé", request=requete)

    with pytest.raises(ErreurClient, match="Agent First n'est pas démarré."):
        client_avec(gestionnaire).envoyer("c1", "Bonjour")


def test_delai_depasse():
    def gestionnaire(requete):
        raise httpx.ReadTimeout("trop long", request=requete)

    with pytest.raises(ErreurClient, match="5 minutes"):
        client_avec(gestionnaire).envoyer("c1", "Bonjour")


def test_reponse_illisible():
    client = client_avec(lambda r: httpx.Response(500, text="plantage"))
    with pytest.raises(ErreurClient, match="code 500"):
        client.envoyer("c1", "Bonjour")
