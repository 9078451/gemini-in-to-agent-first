"""Pilote des API au format OpenAI : OpenAI, Gemini API, Mistral, Groq, OpenRouter,
DeepSeek, xAI, Ollama (sur ce PC) et tout serveur compatible (LM Studio…).

`POST {base}/chat/completions` en flux (SSE) : le texte arrive morceau par morceau.
Une limite (429) ou une panne (5xx) est réessayée deux fois avant la première ligne de
réponse ; jamais après (le début de réponse est gardé dans l'erreur).
"""
import json
import logging
import time
from typing import Callable

import httpx

from fournisseurs.catalogue import CATALOGUE
from fournisseurs.commun import EFFORTS, NIVEAUX, Ecriture, modele_choisi
from fournisseurs.memoire import MemoireFils
from fournisseurs.reglages import ReglagesFournisseurs
from pilote.erreurs import (
    CleRefusee, DemandeRefusee, FournisseurIndisponible, Interrompu, LimiteFournisseur, ModeleIntrouvable,
)
from pilote.modeles import Modes, Option, ResultatGemini

journal = logging.getLogger(__name__)

DELAI_DEFAUT = 180.0
ATTENTES_REPRISE = (1.0, 3.0)  # s avant le 2ᵉ puis le 3ᵉ essai
ATTENTE_MAX = 10.0  # s : `retry-after` plus long → pas d'essai de plus
# Pas des modèles de discussion : retirés de la liste.
NON_CHAT = ("embed", "whisper", "tts", "dall-e", "moderation", "audio", "transcribe", "image", "realtime",
            "speech", "rerank", "guard", "ocr")
MODELES_AFFICHES = 8  # proposés tant que l'utilisateur n'a pas choisi les siens


class _Reessayer(Exception):
    def __init__(self, erreur: Exception, attente: float | None = None) -> None:
        self.erreur = erreur
        self.attente = attente


def message_erreur(reponse: httpx.Response) -> str:
    """Le message d'erreur d'une réponse : {"error": {"message"}}, {"error": "…"}, {"message"} ou le texte."""
    try:
        corps = reponse.json()
    except ValueError:
        return reponse.text.strip()[:300] or f"code {reponse.status_code}"
    erreur = corps.get("error", corps) if isinstance(corps, dict) else corps
    if isinstance(erreur, dict):
        return str(erreur.get("message") or erreur.get("msg") or erreur)[:300]
    return str(erreur)[:300]


def trier_modeles(donnees: list[dict]) -> list[str]:
    """Les modèles de discussion, du plus récent au plus ancien (puis par nom)."""
    modeles = []
    for d in donnees:
        identifiant = str(d.get("id", "")).removeprefix("models/")
        if identifiant and not any(mot in identifiant.lower() for mot in NON_CHAT):
            modeles.append((-(d.get("created") or 0), identifiant))
    return [identifiant for _, identifiant in sorted(set(modeles))]


class PiloteOpenAI:
    def __init__(
        self,
        fournisseur: str,
        reglages: ReglagesFournisseurs,
        memoire: MemoireFils,
        client: httpx.Client | None = None,
        attentes: tuple[float, ...] = ATTENTES_REPRISE,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._id = fournisseur
        self._f = CATALOGUE[fournisseur]
        self._reglages = reglages
        self._memoire = memoire
        self._client = client or httpx.Client(follow_redirects=True)
        self._attentes = attentes
        self._dormir = dormir
        self._sans_effort: set[str] = set()  # modèles qui refusent `reasoning_effort`
        self._lus: list[str] = []

    # ---- contrat Pilote ---------------------------------------------------

    def preparer(self) -> None:
        pass

    def est_connecte(self) -> bool:
        return bool(self._reglages.cle(self._id)) or not self._f.cle_requise

    def lister_modes(self) -> Modes:
        modeles = self.lister_modeles()
        return Modes([Option(m, "", i == 0) for i, m in enumerate(modeles)], NIVEAUX if self._f.niveaux else [])

    def lister_modeles(self) -> list[str]:
        """Les modèles de discussion proposés par le fournisseur (`GET /models`)."""
        try:
            reponse = self._client.get(f"{self._base()}/models", headers=self._entetes(), timeout=10)
        except httpx.HTTPError as e:
            raise self._injoignable(e) from e
        if reponse.status_code >= 400:
            erreur = self._erreur_http(reponse, None)
            raise erreur.erreur if isinstance(erreur, _Reessayer) else erreur
        donnees = reponse.json()
        self._lus = trier_modeles(donnees.get("data", []) if isinstance(donnees, dict) else donnees)
        return self._lus

    def envoyer(
        self,
        adresse: str | None,
        texte: str,
        modele: str | None = None,
        niveau: str | None = None,
        delai: float | None = None,
        au_fil: Callable[[str, str], None] | None = None,
    ) -> ResultatGemini:
        debut = time.monotonic()
        modele = modele_choisi(self._id, self._reglages, modele, self._lus)
        messages = self._memoire.lire(adresse) + [{"role": "user", "content": texte}]
        adresse = adresse or self._memoire.nouvelle_adresse(self._id)
        corps = {"model": modele, "messages": messages, "stream": True}
        effort = EFFORTS.get(niveau or "") if self._f.effort_openai and modele not in self._sans_effort else None
        if effort:
            corps["reasoning_effort"] = effort
        ecriture = Ecriture(au_fil)
        try:
            self._flux(corps, delai or DELAI_DEFAUT, ecriture)
        except Interrompu:
            if ecriture.texte:
                self._memoire.ecrire(adresse, messages + [{"role": "assistant", "content": ecriture.texte}])
            raise Interrompu(ecriture.texte, ecriture.html_final(), adresse)
        self._memoire.ecrire(adresse, messages + [{"role": "assistant", "content": ecriture.texte}])
        return ResultatGemini(
            reponse=ecriture.texte.strip(), adresse=adresse, html=ecriture.html_final(), modele=modele,
            niveau=niveau if "reasoning_effort" in corps else None, duree=round(time.monotonic() - debut, 1),
        )

    # ---- interne ----------------------------------------------------------

    def _base(self) -> str:
        return self._reglages.url(self._id).rstrip("/")

    def _entetes(self) -> dict:
        cle = self._reglages.cle(self._id)
        if not cle and self._f.cle_requise:
            raise CleRefusee(self._f.nom)
        entetes = {"Authorization": f"Bearer {cle}"} if cle else {}
        if self._id == "openrouter":  # facultatif : nomme l'app dans le tableau de bord d'OpenRouter
            entetes["X-Title"] = "agent.first"
        return entetes

    def _flux(self, corps: dict, delai: float, ecriture: Ecriture) -> None:
        essais = len(self._attentes) + 1
        for essai in range(essais):
            try:
                self._un_essai(corps, delai, ecriture)
                return
            except _Reessayer as r:
                if essai == essais - 1 or (r.attente is not None and r.attente > ATTENTE_MAX):
                    raise r.erreur
                attente = r.attente if r.attente is not None else self._attentes[essai]
                journal.info("%s : nouvel essai dans %.0f s (%s)", self._f.nom, attente, r.erreur)
                self._dormir(attente)

    def _un_essai(self, corps: dict, delai: float, ecriture: Ecriture) -> None:
        url = f"{self._base()}/chat/completions"
        try:
            with self._client.stream("POST", url, json=corps, headers=self._entetes(),
                                     timeout=httpx.Timeout(delai, connect=10.0)) as reponse:
                if reponse.status_code >= 400:
                    reponse.read()
                    if reponse.status_code == 400 and "reasoning_effort" in corps and "reasoning" in message_erreur(reponse).lower():
                        # Ce modèle ne réfléchit pas sur commande : renvoyé sans niveau.
                        self._sans_effort.add(corps["model"])
                        del corps["reasoning_effort"]
                        raise _Reessayer(DemandeRefusee(self._f.nom, message_erreur(reponse)), attente=0.0)
                    raise self._erreur_http(reponse, corps["model"])
                self._lire(reponse, ecriture)
        except httpx.TimeoutException as e:
            if ecriture.texte:
                raise FournisseurIndisponible(self._f.nom, f"plus rien reçu depuis {delai:.0f} s", ecriture.texte) from e
            raise FournisseurIndisponible(self._f.nom, f"pas de réponse après {delai:.0f} s") from e
        except httpx.HTTPError as e:
            if ecriture.texte:  # coupé au milieu : pas de nouvel essai, le début est gardé
                raise FournisseurIndisponible(self._f.nom, "connexion coupée pendant la réponse", ecriture.texte) from e
            raise self._injoignable(e) from e

    def _lire(self, reponse: httpx.Response, ecriture: Ecriture) -> None:
        for ligne in reponse.iter_lines():
            if not ligne.startswith("data:"):
                ecriture.verifier()  # signal de maintien : un arrêt demandé est vu
                continue
            donnee = ligne[5:].strip()
            if donnee == "[DONE]":
                return
            try:
                morceau = json.loads(donnee)
            except ValueError:
                continue
            if isinstance(morceau, dict) and morceau.get("error"):
                erreur = morceau["error"]
                detail = erreur.get("message", str(erreur)) if isinstance(erreur, dict) else str(erreur)
                if ecriture.texte:
                    raise FournisseurIndisponible(self._f.nom, detail, ecriture.texte)
                raise _Reessayer(FournisseurIndisponible(self._f.nom, detail))
            for choix in morceau.get("choices") or []:
                contenu = (choix.get("delta") or {}).get("content")
                if contenu:
                    ecriture.ajouter(contenu)
                else:
                    ecriture.verifier()

    def _erreur_http(self, reponse: httpx.Response, modele: str | None) -> Exception:
        code, detail = reponse.status_code, message_erreur(reponse)
        if code in (401, 403):
            return CleRefusee(self._f.nom)
        if code == 404 and modele:
            return ModeleIntrouvable(modele, self._f.nom)
        if code == 429:
            return _Reessayer(LimiteFournisseur(self._f.nom, detail), self._retry_after(reponse))
        if code >= 500:
            return _Reessayer(FournisseurIndisponible(self._f.nom, f"erreur {code} : {detail}"), self._retry_after(reponse))
        return DemandeRefusee(self._f.nom, detail)

    def _injoignable(self, erreur: Exception) -> FournisseurIndisponible:
        detail = f"connexion impossible à {self._base()}"
        if self._id == "ollama":
            detail += " (Ollama est-il lancé ?)"
        return FournisseurIndisponible(self._f.nom, f"{detail} — {type(erreur).__name__}")

    @staticmethod
    def _retry_after(reponse: httpx.Response) -> float | None:
        try:
            return float(reponse.headers.get("retry-after", ""))
        except ValueError:
            return None
