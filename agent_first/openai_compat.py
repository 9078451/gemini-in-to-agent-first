"""Ce qu'il faut pour parler comme l'API d'OpenAI (beaucoup d'outils savent déjà
l'appeler), et pour présenter les étapes Cowork en anglais aux autres programmes.

Fonctions pures : tout ce qui touche à Gemini, à l'historique ou au réseau est dans
`api_reseau`.
"""
import hashlib
import json
import re
import socket
import time
import uuid
from typing import Iterator

EFFORTS = {"minimal": "Min.", "low": "Min.", "medium": "Moyen", "high": "Max."}
ROLES_SYSTEME = ("system", "developer")


def niveau_depuis_effort(effort: str | None) -> str | None:
    """`reasoning_effort` d'OpenAI → niveau de réflexion de Gemini."""
    return EFFORTS.get(effort.lower()) if effort else None


def texte_message(contenu) -> str:
    """Le texte d'un message OpenAI (chaîne, ou liste de morceaux dont on garde le texte)."""
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "\n".join(
            m.get("text", "") for m in contenu if isinstance(m, dict) and m.get("type") in ("text", "input_text")
        )
    return "" if contenu is None else str(contenu)


def empreinte(modele: str | None, messages: list[dict]) -> str:
    """Reconnaît un historique déjà échangé, pour continuer la même conversation Gemini."""
    normalises = [{"role": m.get("role"), "content": texte_message(m.get("content"))} for m in messages]
    brut = json.dumps([modele, normalises], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def mettre_a_plat(messages: list[dict]) -> str:
    """Tout l'historique en un seul message, pour une conversation Gemini neuve."""
    systeme = [texte_message(m.get("content")) for m in messages if m.get("role") in ROLES_SYSTEME]
    echanges = [m for m in messages if m.get("role") not in ROLES_SYSTEME]
    if not echanges:
        return "\n\n".join(systeme)
    dernier, avant = echanges[-1], echanges[:-1]
    if not systeme and not avant:
        return texte_message(dernier.get("content"))
    parties = []
    if systeme:
        parties.append("[System instructions]\n" + "\n\n".join(systeme))
    if avant:
        lignes = [
            f"{'Assistant' if m.get('role') == 'assistant' else 'User'}: {texte_message(m.get('content'))}" for m in avant
        ]
        parties.append("[Conversation so far]\n" + "\n\n".join(lignes))
    parties.append("[New message]\n" + texte_message(dernier.get("content")))
    return "\n\n".join(parties)


def nettoyer_reponse(texte: str) -> str:
    """Le texte lu dans Gemini commence par « Gemini a dit » (titre pour lecteur d'écran)."""
    return re.sub(r"^\s*Gemini a dit\s*\n?", "", texte, count=1).strip()


def estimer_jetons(texte: str) -> int:
    return max(1, len(texte) // 4)


def completion(contenu: str, modele: str, invite: str) -> dict:
    entree, sortie = estimer_jetons(invite), estimer_jetons(contenu)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": modele,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": contenu}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": entree, "completion_tokens": sortie, "total_tokens": entree + sortie},
    }


def morceaux(contenu: str, modele: str) -> Iterator[str]:
    """La réponse en flux SSE au format OpenAI : Gemini web étant lu à la fin, un seul morceau."""
    base = {"id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion.chunk",
            "created": int(time.time()), "model": modele}
    for choix in (
        {"index": 0, "delta": {"role": "assistant", "content": contenu}, "finish_reason": None},
        {"index": 0, "delta": {}, "finish_reason": "stop"},
    ):
        yield f"data: {json.dumps({**base, 'choices': [choix]}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


# Les étapes Cowork sont gardées en français ; l'API réseau les présente en anglais.
TYPES = {
    "plan": "plan", "action": "action", "resultat": "result", "saute": "skipped",
    "demande": "approval_required", "autorise": "auto_approved", "refus": "refused",
    "erreur_format": "format_error", "erreur_gemini": "gemini_error", "relance_fin": "done_refused",
    "termine": "done", "question": "question", "limite": "limit_reached", "arret": "stopped",
    "erreur": "error", "statut": "status", "processus": "processes",
}
CLES = {
    "etape": "step", "champs": "fields", "corps": "output", "raison": "reason", "resume": "summary",
    "etapes": "steps", "texte": "text", "fait": "done", "bilan": "report", "crees": "created",
    "modifies": "modified", "supprimes": "deleted", "commandes": "commands", "code": "exit_code",
    "plan_inacheve": "unfinished_steps", "processus": "processes", "liste": "processes",
    "commande": "command", "depuis": "since", "actif": "running", "statut": "status",
    "evenements": "events",
}
CLES_INTERNES = {"tache"}  # l'état interne d'une tâche en pause n'a rien à faire dehors


def vers_api(valeur):
    if isinstance(valeur, list):
        return [vers_api(v) for v in valeur]
    if not isinstance(valeur, dict):
        return valeur
    traduit = {}
    for cle, v in valeur.items():
        if cle in CLES_INTERNES:
            continue
        traduit[CLES.get(cle, cle)] = TYPES.get(v, v) if cle == "type" and isinstance(v, str) else vers_api(v)
    return traduit


def adresse_reseau() -> str:
    """L'adresse du PC sur le réseau local, à donner aux autres appareils (aucun paquet n'est envoyé)."""
    par_defaut = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            par_defaut = s.getsockname()[0]
    except OSError:
        pass
    try:
        toutes = [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        toutes = []
    return choisir_adresse(par_defaut, toutes)


def choisir_adresse(par_defaut: str | None, toutes: list[str]) -> str:
    """La route par défaut peut passer par un VPN (100.x) : on préfère une adresse privée du
    réseau local, et en dernier l'adaptateur de VirtualBox (192.168.56.x)."""

    def rang(adresse: str) -> int:
        if adresse.startswith("192.168.56."):
            return 2
        if adresse.startswith("192.168."):
            return 0
        if adresse.startswith("10.") or re.match(r"172\.(1[6-9]|2\d|3[01])\.", adresse):
            return 1
        return 3

    candidates = [a for a in dict.fromkeys([par_defaut, *toutes]) if a and not a.startswith(("127.", "169.254."))]
    return min(candidates, key=rang) if candidates else "127.0.0.1"
