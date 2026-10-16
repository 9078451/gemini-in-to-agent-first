"""Exécuter les actions de Gemini, toujours bornées au dossier de travail.

Les actions sur fichiers (lister, lire, chercher, creer, modifier, supprimer)
ne peuvent pas sortir du dossier de travail : un chemin qui s'en échappe est
refusé ici, dans le code. Seule « commande » peut atteindre l'extérieur, et
c'est l'analyse de sûreté qui la couvre.
"""
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cowork.format import Action


class HorsDossier(Exception):
    pass


@dataclass(frozen=True)
class Resultat:
    ok: bool
    corps: str
    diff: str | None = None


def lancer_powershell(texte: str, dossier: Path, delai: float) -> tuple[int, str]:
    """Lance une commande PowerShell dans `dossier` ; renvoie (code, sortie)."""
    acheve = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", texte],
        cwd=dossier,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=delai,
    )
    return acheve.returncode, (acheve.stdout or "") + (acheve.stderr or "")


class Executeur:
    def __init__(
        self,
        dossier: Path,
        delai: float,
        taille_max: int,
        lancer: Callable[[str, Path, float], tuple[int, str]] = lancer_powershell,
    ) -> None:
        self._dossier = dossier
        self._delai = delai
        self._taille_max = taille_max
        self._lancer = lancer

    def executer(self, action: Action) -> Resultat:
        if action.nom == "commande":
            return self._commande(action.champs.get("texte", ""))
        try:
            return self._action_fichier(action)
        except HorsDossier:
            return Resultat(False, "chemin hors du dossier de travail")

    def _resoudre(self, chemin: str) -> Path:
        cible = (self._dossier / chemin).resolve()
        if cible != self._dossier.resolve() and not cible.is_relative_to(self._dossier.resolve()):
            raise HorsDossier(chemin)
        return cible

    def _action_fichier(self, action: Action) -> Resultat:
        c = action.champs
        if action.nom == "lister":
            cible = self._resoudre(c.get("chemin", "."))
            noms = sorted(p.name + ("/" if p.is_dir() else "") for p in cible.iterdir())
            return Resultat(True, "\n".join(noms) or "(dossier vide)")
        if action.nom == "lire":
            texte = self._resoudre(c["chemin"]).read_text(encoding="utf-8", errors="replace")
            return Resultat(True, self._couper(texte))
        if action.nom == "chercher":
            return self._chercher(c["motif"], c.get("glob", "**/*"))
        if action.nom == "creer":
            cible = self._resoudre(c["chemin"])
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_text(c.get("contenu", ""), encoding="utf-8")
            return Resultat(True, f"{c['chemin']} écrit")
        if action.nom == "modifier":
            return self._modifier(c["chemin"], c["avant"], c["apres"])
        if action.nom == "supprimer":
            return self._supprimer(c["chemin"])
        return Resultat(False, f"action inconnue : {action.nom}")

    def _chercher(self, motif: str, glob: str) -> Resultat:
        if ".." in glob.replace("\\", "/").split("/") or Path(glob).is_absolute() or Path(glob).drive:
            raise HorsDossier(glob)
        racine = self._dossier.resolve()
        lignes = []
        for fichier in self._dossier.glob(glob):
            if not fichier.is_file() or not fichier.resolve().is_relative_to(racine):
                continue
            try:
                for i, ligne in enumerate(fichier.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if motif in ligne:
                        lignes.append(f"{fichier.relative_to(self._dossier)}:{i}: {ligne.strip()}")
            except OSError:
                continue
        return Resultat(True, self._couper("\n".join(lignes)) or "(aucune occurrence)")

    def _modifier(self, chemin: str, avant: str, apres: str) -> Resultat:
        cible = self._resoudre(chemin)
        texte = cible.read_text(encoding="utf-8", errors="replace")
        if avant not in texte:
            return Resultat(False, "passage « avant » introuvable dans le fichier")
        cible.write_text(texte.replace(avant, apres, 1), encoding="utf-8")
        diff = "\n".join([*(f"-{l}" for l in avant.splitlines()), *(f"+{l}" for l in apres.splitlines())])
        return Resultat(True, f"{chemin} modifié", diff=diff)

    def _supprimer(self, chemin: str) -> Resultat:
        cible = self._resoudre(chemin)
        if cible.is_dir():
            import shutil

            shutil.rmtree(cible)
        else:
            cible.unlink()
        return Resultat(True, f"{chemin} supprimé")

    def _commande(self, texte: str) -> Resultat:
        try:
            code, sortie = self._lancer(texte, self._dossier, self._delai)
        except subprocess.TimeoutExpired:
            return Resultat(False, f"commande trop longue (plus de {self._delai:.0f} s)")
        corps = self._couper(sortie.strip())
        return Resultat(code == 0, corps or f"(code {code})")

    def _couper(self, texte: str) -> str:
        if len(texte) <= self._taille_max:
            return texte
        return texte[: self._taille_max] + "\n…(coupé)"
