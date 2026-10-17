import json

from agent_first.openai_compat import (
    completion,
    empreinte,
    mettre_a_plat,
    morceaux,
    nettoyer_reponse,
    niveau_depuis_effort,
    texte_message,
    vers_api,
)


def test_niveau_depuis_effort():
    assert niveau_depuis_effort("low") == "Min."
    assert niveau_depuis_effort("medium") == "Moyen"
    assert niveau_depuis_effort("HIGH") == "Max."
    assert niveau_depuis_effort(None) is None
    assert niveau_depuis_effort("extreme") is None


def test_texte_message():
    assert texte_message("a") == "a"
    assert texte_message([{"type": "text", "text": "a"}, {"type": "image_url"}, {"type": "text", "text": "b"}]) == "a\nb"
    assert texte_message(None) == ""


def test_un_seul_message_tel_quel():
    assert mettre_a_plat([{"role": "user", "content": "Bonjour"}]) == "Bonjour"


def test_mettre_a_plat_avec_systeme_et_historique():
    texte = mettre_a_plat([
        {"role": "system", "content": "Sois bref."},
        {"role": "user", "content": "Salut"},
        {"role": "assistant", "content": "Bonjour !"},
        {"role": "user", "content": "Ça va ?"},
    ])
    assert texte.startswith("[System instructions]\nSois bref.")
    assert "[Conversation so far]\nUser: Salut\n\nAssistant: Bonjour !" in texte
    assert texte.endswith("[New message]\nÇa va ?")


def test_empreinte():
    messages = [{"role": "user", "content": "a"}]
    assert empreinte("4 Argon", messages) == empreinte("4 Argon", [{"role": "user", "content": [{"type": "text", "text": "a"}]}])
    assert empreinte("4 Argon", messages) != empreinte("3.1 Pro", messages)
    assert empreinte(None, messages) != empreinte(None, messages + [{"role": "assistant", "content": "b"}])


def test_completion():
    reponse = completion("Bonjour", "4 Argon", "Salut")
    assert reponse["object"] == "chat.completion" and reponse["model"] == "4 Argon"
    assert reponse["choices"][0]["message"] == {"role": "assistant", "content": "Bonjour"}
    assert reponse["choices"][0]["finish_reason"] == "stop"
    assert reponse["usage"]["total_tokens"] == reponse["usage"]["prompt_tokens"] + reponse["usage"]["completion_tokens"]


def test_morceaux():
    lignes = list(morceaux("Bonjour", "4 Argon"))
    assert lignes[-1] == "data: [DONE]\n\n"
    premier = json.loads(lignes[0][len("data: "):])
    assert premier["object"] == "chat.completion.chunk" and premier["choices"][0]["delta"]["content"] == "Bonjour"


def test_nettoyer_reponse():
    assert nettoyer_reponse("Gemini a dit\nBonjour") == "Bonjour"
    assert nettoyer_reponse("Bonjour") == "Bonjour"


def test_vers_api():
    assert vers_api({"type": "resultat", "corps": "x", "etape": 3}) == {"type": "result", "output": "x", "step": 3}
    termine = vers_api({"type": "termine", "resume": "ok", "bilan": {"crees": ["a"], "commandes": [{"texte": "dir", "code": 0}],
                                                                       "plan_inacheve": []}})
    assert termine == {"type": "done", "summary": "ok",
                       "report": {"created": ["a"], "commands": [{"text": "dir", "exit_code": 0}], "unfinished_steps": []}}
    assert vers_api({"type": "question", "question": "?", "tache": {"plan": []}}) == {"type": "question", "question": "?"}
    assert vers_api({"type": "demande", "action": "delete", "raison": "x"})["type"] == "approval_required"


def test_choisir_adresse_prefere_le_reseau_local():
    from agent_first.openai_compat import choisir_adresse

    # Vrai cas : la route par défaut passe par un VPN (100.x), VirtualBox ajoute 192.168.56.1.
    assert choisir_adresse("100.120.238.218", ["100.120.238.218", "192.168.1.160", "192.168.56.1"]) == "192.168.1.160"
    assert choisir_adresse("10.0.0.5", ["192.168.56.1", "10.0.0.5"]) == "10.0.0.5"
    assert choisir_adresse(None, ["127.0.0.1", "169.254.3.4", "100.64.1.1"]) == "100.64.1.1"
    assert choisir_adresse(None, []) == "127.0.0.1"


def test_vers_api_traduit_les_temps():
    assert vers_api({"type": "tour", "gemini": 12.5}) == {"type": "round", "gemini": 12.5}
    assert vers_api({"bilan": {"temps": {"gemini": 1.0, "actions": 2.0}}}) == {"report": {"timing": {"gemini": 1.0, "actions": 2.0}}}


def test_vers_api_conversation_neuve():
    assert vers_api({"type": "relais", "corps": "x"})["type"] == "new_gemini_chat"
