"""Réglages des fournisseurs : actifs ou non, clés API, modèles affichés, secours.

Gardés dans `donnees/fournisseurs.json` (hors git), comme la clé de l'API réseau.
Une clé n'est jamais renvoyée en entier à la page : `publics()` la masque.
"""
import copy
import json
import logging
import os
import threading
from pathlib import Path

from fournisseurs.catalogue import CATALOGUE, PAR_DEFAUT

journal = logging.getLogger(__name__)

SECOURS_VIDE = {"actif": False, "fournisseur": None, "modele": None}


def masquer(cle: str | None) -> str | None:
    if not cle:
        return None
    return "••••" + cle[-4:] if len(cle) > 8 else "••••"


class ReglagesFournisseurs:
    def __init__(self, fichier: Path) -> None:
        self._fichier = fichier
        self._verrou = threading.Lock()
        self._donnees = self._charger()

    # ---- lecture ----------------------------------------------------------

    def config(self, identifiant: str) -> dict:
        """actif, cle, modeles (liste choisie, vide = suggérés), url (adresse perso ou None)."""
        with self._verrou:
            brut = self._donnees["fournisseurs"].get(identifiant, {})
            return {
                "actif": identifiant == PAR_DEFAUT or bool(brut.get("actif")),
                "cle": brut.get("cle") or None,
                "modeles": list(brut.get("modeles") or []),
                "url": brut.get("url") or None,
            }

    def actifs(self) -> list[str]:
        return [i for i in CATALOGUE if self.config(i)["actif"]]

    def cle(self, identifiant: str) -> str | None:
        return self.config(identifiant)["cle"]

    def url(self, identifiant: str) -> str:
        return self.config(identifiant)["url"] or CATALOGUE[identifiant].base_url

    def secours(self) -> dict:
        with self._verrou:
            return {**SECOURS_VIDE, **self._donnees.get("secours", {})}

    def publics(self) -> list[dict]:
        """Pour la page : tout sauf les clés (masquées)."""
        publics = []
        for identifiant, f in CATALOGUE.items():
            c = self.config(identifiant)
            publics.append({
                "id": identifiant, "nom": f.nom, "type": f.type, "actif": c["actif"],
                "cle": masquer(c["cle"]), "cle_requise": f.cle_requise, "modeles": c["modeles"],
                "url": c["url"] or f.base_url or f.url_site, "url_modifiable": identifiant in ("ollama", "perso"),
                "aide": f.aide, "niveaux": f.niveaux,
            })
        return publics

    # ---- écriture ---------------------------------------------------------

    def enregistrer(self, identifiant: str, *, actif: bool | None = None, cle: str | None = None,
                    modeles: list[str] | None = None, url: str | None = None) -> None:
        """Change ce qui est donné ; `cle=""` efface la clé."""
        if identifiant not in CATALOGUE:
            raise KeyError(identifiant)
        with self._verrou:
            brut = self._donnees["fournisseurs"].setdefault(identifiant, {})
            if actif is not None:
                brut["actif"] = actif
            if cle is not None:
                brut["cle"] = cle.strip()
            if modeles is not None:
                brut["modeles"] = [m for m in dict.fromkeys(m.strip() for m in modeles) if m]
            if url is not None:
                brut["url"] = url.strip().rstrip("/")
            self._sauver()

    def regler_secours(self, actif: bool, fournisseur: str | None, modele: str | None) -> None:
        if fournisseur is not None and fournisseur not in CATALOGUE:
            raise KeyError(fournisseur)
        with self._verrou:
            self._donnees["secours"] = {"actif": actif, "fournisseur": fournisseur, "modele": modele}
            self._sauver()

    # ---- interne ----------------------------------------------------------

    def _charger(self) -> dict:
        vide = {"fournisseurs": {}, "secours": dict(SECOURS_VIDE)}
        try:
            donnees = json.loads(self._fichier.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return vide
        except (OSError, ValueError):
            mis_de_cote = self._fichier.with_name(self._fichier.stem + ".illisible.json")
            try:
                os.replace(self._fichier, mis_de_cote)
            except OSError:
                pass
            journal.warning("%s illisible, mis de côté dans %s", self._fichier, mis_de_cote)
            return vide
        if not isinstance(donnees, dict) or not isinstance(donnees.get("fournisseurs", {}), dict):
            return vide
        return {"fournisseurs": donnees.get("fournisseurs", {}), "secours": donnees.get("secours", dict(SECOURS_VIDE))}

    def _sauver(self) -> None:
        """Appelé sous le verrou : écrit dans un fichier à part, puis le met à la place."""
        self._fichier.parent.mkdir(parents=True, exist_ok=True)
        provisoire = self._fichier.with_suffix(".tmp")
        provisoire.write_text(json.dumps(copy.deepcopy(self._donnees), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(provisoire, self._fichier)
