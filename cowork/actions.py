"""Exécuter les actions de Gemini, toujours bornées au dossier de travail.

Les actions sur fichiers ne peuvent pas sortir du dossier de travail : un chemin
qui s'en échappe est refusé ici, dans le code. Seules les commandes (`run`,
`start`) peuvent atteindre l'extérieur, et c'est l'analyse de sûreté qui les couvre.

Rien ne lève : chaque action donne un `Resultat`, OK ou en erreur, que Gemini lit
pour corriger. Une exception ferait tomber toute la tâche.
"""
import difflib
import os
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from cowork.catalogue import Action, Resultat, valider
from cowork.visite import visiter

if TYPE_CHECKING:
    from cowork.processus import GestionnaireProcessus

__all__ = ["Executeur", "Resultat", "HorsDossier", "lancer_powershell", "tuer_arbre"]

LIGNES_DIFF_MAX = 200
LIGNES_PASSAGE_MAX = 5000  # au-delà, on ne cherche pas de passage proche


class HorsDossier(Exception):
    pass


# Sans cela, PowerShell 5.1 écrit sa sortie dans la page de code de la console (cp850) :
# lue en UTF-8, « Répertoire » devenait « R�pertoire ».
_SORTIE_UTF8 = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $OutputEncoding = [Text.Encoding]::UTF8; "


def commande_powershell(texte: str) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SORTIE_UTF8 + texte]


def tuer_arbre(pid: int) -> None:
    """Tue un processus et tous ses enfants (un python lancé par PowerShell survit sinon)."""
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)


def lancer_powershell(texte: str, dossier: Path, delai: float) -> tuple[int, str]:
    """Lance une commande PowerShell dans `dossier` ; renvoie (code, sortie).
    Au-delà de `delai`, tout l'arbre de processus est tué et TimeoutExpired relevée."""
    processus = subprocess.Popen(
        commande_powershell(texte),
        cwd=dossier,
        env={**os.environ, "PYTHONUTF8": "1"},  # un script Python lancé écrit lui aussi en UTF-8
        stdin=subprocess.DEVNULL,  # un input() échoue tout de suite au lieu d'attendre le délai
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        sortie, erreurs = processus.communicate(timeout=delai)
    except subprocess.TimeoutExpired:
        tuer_arbre(processus.pid)
        try:
            processus.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise
    return processus.returncode, (sortie or "") + (erreurs or "")


class Executeur:
    def __init__(
        self,
        dossier: Path,
        delai: float,
        taille_max: int,
        lancer: Callable[[str, Path, float], tuple[int, str]] = lancer_powershell,
        processus: "GestionnaireProcessus | None" = None,
        ports_interdits: frozenset[int] = frozenset(),
        delai_visite: float = 10.0,
    ) -> None:
        self._dossier = dossier
        self._delai = delai
        self._taille_max = taille_max
        self._lancer = lancer
        self._processus = processus
        self._ports_interdits = ports_interdits
        self._delai_visite = delai_visite
        self._aiguillage: dict[str, Callable[[dict], Resultat]] = {
            "list": self._lister,
            "read": self._lire,
            "search": self._chercher,
            "create": self._creer,
            "edit": self._modifier,
            "delete": self._supprimer,
            "run": self._commande,
            "start": self._demarrer,
            "logs": self._sortie,
            "stop": self._arreter,
            "visit": self._visiter,
        }

    def executer(self, action: Action) -> Resultat:
        erreur = valider(action)
        if erreur:
            return Resultat(False, erreur)
        faire = self._aiguillage.get(action.nom)
        if faire is None:
            return Resultat(False, f'"{action.nom}" is handled by Agent First, not executed')
        chemin = _affiche(str(action.champs.get("path") or ""))
        try:
            return faire(action.champs)
        except HorsDossier:
            return Resultat(False, "path outside the working folder (refused)")
        except FileNotFoundError:
            return Resultat(False, f"not found: {chemin}")
        except NotADirectoryError:
            return Resultat(False, f"not a folder: {chemin}")
        except (IsADirectoryError, PermissionError):
            return Resultat(False, f"cannot access {chemin}: it is a folder, or access is denied")
        except Exception as e:  # le dernier filet : Gemini lit l'erreur et corrige
            return Resultat(False, f"{type(e).__name__}: {e}")

    # ---- fichiers -------------------------------------------------------

    def _resoudre(self, chemin: str) -> Path:
        racine = self._dossier.resolve()
        cible = (self._dossier / chemin.replace("\\", "/")).resolve()
        if cible != racine and not cible.is_relative_to(racine):
            raise HorsDossier(chemin)
        return cible

    def _lister(self, c: dict) -> Resultat:
        cible = self._resoudre(c.get("path") or ".")
        if cible.exists() and not cible.is_dir():
            raise NotADirectoryError(c.get("path"))
        noms = sorted(p.name + ("/" if p.is_dir() else "") for p in cible.iterdir())
        return Resultat(True, "\n".join(noms) or "(empty folder)")

    def _lire(self, c: dict) -> Resultat:
        return Resultat(True, self._couper(_lire_texte(self._resoudre(c["path"]))))

    def _chercher(self, c: dict) -> Resultat:
        motif, glob = c["pattern"], c.get("glob") or "**/*"
        if ".." in glob.replace("\\", "/").split("/") or Path(glob).is_absolute() or Path(glob).drive:
            raise HorsDossier(glob)
        racine = self._dossier.resolve()
        lignes = []
        for fichier in self._dossier.glob(glob):
            if not fichier.is_file() or not fichier.resolve().is_relative_to(racine):
                continue
            try:
                for i, ligne in enumerate(_lire_texte(fichier).splitlines(), 1):
                    if motif in ligne:
                        lignes.append(f"{fichier.relative_to(self._dossier).as_posix()}:{i}: {ligne.strip()}")
            except OSError:
                continue
        return Resultat(True, self._couper("\n".join(lignes)) or "(no match)")

    def _creer(self, c: dict) -> Resultat:
        chemin, contenu = _affiche(c["path"]), c["content"]
        cible = self._resoudre(chemin)
        ancien = _lire_texte(cible) if cible.is_file() else None
        cible.parent.mkdir(parents=True, exist_ok=True)
        _ecrire(cible, contenu)
        lignes = len(contenu.splitlines())
        taille = f"{lignes} line{'s' if lignes != 1 else ''}"
        if ancien is None:
            return Resultat(True, f"{chemin} created ({taille})", effet=("cree", chemin))
        return Resultat(True, f"{chemin} rewritten ({taille})", diff=_diff(ancien, contenu), effet=("modifie", chemin))

    def _modifier(self, c: dict) -> Resultat:
        chemin, avant, apres = _affiche(c["path"]), c["old"], c["new"]
        if not avant:
            return Resultat(False, '"old" must not be empty')
        cible = self._resoudre(chemin)
        texte = _lire_texte(cible)
        nombre = texte.count(avant)
        if nombre == 0:
            return Resultat(False, f'"old" text not found in {chemin}. {_passage_proche(texte, avant)}')
        if nombre > 1:
            return Resultat(False, f'"old" text appears {nombre} times in {chemin}; include more surrounding lines so it is unique')
        nouveau = texte.replace(avant, apres, 1)
        _ecrire(cible, nouveau)
        return Resultat(True, f"{chemin} edited", diff=_diff(texte, nouveau), effet=("modifie", chemin))

    def _supprimer(self, c: dict) -> Resultat:
        chemin = _affiche(c["path"])
        cible = self._resoudre(chemin)
        if cible == self._dossier.resolve():
            return Resultat(False, "the working folder itself cannot be deleted")
        if cible.is_dir():
            shutil.rmtree(cible)
        else:
            cible.unlink()
        return Resultat(True, f"{chemin} deleted", effet=("supprime", chemin))

    # ---- commandes, processus, visite -----------------------------------

    def _commande(self, c: dict) -> Resultat:
        try:
            code, sortie = self._lancer(c["command"], self._dossier, self._delai)
        except subprocess.TimeoutExpired:
            return Resultat(
                False,
                f"command took more than {self._delai:.0f} s and was stopped; use start for long-running processes",
            )
        return Resultat(code == 0, self._couper(sortie.strip()) or "(no output)", code=code)

    def _demarrer(self, c: dict) -> Resultat:
        if self._processus is None:
            return Resultat(False, "background processes are not available here")
        return self._processus.demarrer(c["command"])

    def _sortie(self, c: dict) -> Resultat:
        if self._processus is None:
            return Resultat(False, "background processes are not available here")
        return self._processus.sortie(c["id"])

    def _arreter(self, c: dict) -> Resultat:
        if self._processus is None:
            return Resultat(False, "background processes are not available here")
        return self._processus.arreter(c["id"])

    def _visiter(self, c: dict) -> Resultat:
        return visiter(
            c["url"], c.get("method") or "GET", c.get("body"), self._ports_interdits, self._delai_visite, self._taille_max
        )

    def _couper(self, texte: str) -> str:
        if len(texte) <= self._taille_max:
            return texte
        return texte[: self._taille_max] + "\n…(cut)"


def _affiche(chemin: str) -> str:
    """Le chemin tel qu'on le montre (bilan, résultats) : barres obliques normales."""
    return chemin.replace("\\", "/")


def _lire_texte(fichier: Path) -> str:
    return fichier.read_text(encoding="utf-8", errors="replace")


def _ecrire(fichier: Path, texte: str) -> None:
    """Écrit `texte` en gardant les fins de ligne d'un fichier existant (LF ou CRLF) :
    sans cela, chaque modification transformait tout un fichier LF en CRLF."""
    fin = None  # nouveau fichier : fins de ligne de Windows, comme avant
    if fichier.is_file():
        fin = "\r\n" if b"\r\n" in fichier.read_bytes() else "\n"
    with open(fichier, "w", encoding="utf-8", newline=fin) as sortie:
        sortie.write(texte)


def _diff(avant: str, apres: str) -> str:
    lignes = [
        l for l in difflib.unified_diff(avant.splitlines(), apres.splitlines(), n=2, lineterm="")
        if not l.startswith(("---", "+++"))
    ]
    if len(lignes) > LIGNES_DIFF_MAX:
        lignes = lignes[:LIGNES_DIFF_MAX] + ["…"]
    return "\n".join(lignes)


def _passage_proche(texte: str, cherche: str) -> str:
    """Le passage du fichier qui ressemble le plus à `cherche` (même nombre de lignes),
    pour que Gemini corrige son « old » du premier coup."""
    lignes = texte.splitlines()[:LIGNES_PASSAGE_MAX]
    taille = max(1, len(cherche.splitlines()))
    meilleur, debut = 0.0, 0
    for i in range(max(1, len(lignes) - taille + 1)):
        comparaison = SequenceMatcher(None, cherche, "\n".join(lignes[i : i + taille]), autojunk=False)
        if comparaison.quick_ratio() <= meilleur:
            continue
        ratio = comparaison.ratio()
        if ratio > meilleur:
            meilleur, debut = ratio, i
    if meilleur < 0.5:
        return "No similar passage found."
    fin = min(debut + taille, len(lignes))
    return f"Closest passage (lines {debut + 1}-{fin}):\n" + "\n".join(lignes[debut:fin])
