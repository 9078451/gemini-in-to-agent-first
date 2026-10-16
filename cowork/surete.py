"""Juger si une action est sûre ou dangereuse, pour décider si on demande l'accord.

Prudent par principe : une suppression, ou une commande non reconnue, est
dangereuse. La liste des motifs est ici, à un seul endroit, pour l'ajuster.
"""
import re
from dataclasses import dataclass

from cowork.format import Action


@dataclass(frozen=True)
class Verdict:
    dangereuse: bool
    raison: str = ""


# Premier mot d'une commande jugée sans risque (lecture, build, test).
COMMANDES_SURES: set[str] = {
    "dir", "ls", "gci", "get-childitem", "type", "cat", "get-content", "echo", "write-output",
    "cd", "pwd", "git", "python", "py", "python3", "node", "npm", "npx", "pnpm", "yarn",
    "pytest", "pip", "where", "findstr", "select-string", "test-path", "measure-object",
}

# (motif insensible à la casse, raison affichée). L'ordre n'importe pas.
MOTIFS_DANGEREUX: list[tuple[str, str]] = [
    (r"remove-item.*-(recurse|force)", "suppression récursive ou forcée"),
    (r"\brd\b|\brmdir\b|\bdel\b|\berase\b", "suppression de fichiers"),
    (r"format-\w+", "formatage d'un disque"),
    (r"stop-computer|restart-computer|shutdown", "arrêt ou redémarrage du PC"),
    (r"stop-service|start-service|^\s*sc\b|set-service", "modification d'un service"),
    (r"\breg\b|hklm:|hkcu:|set-itemproperty.*hk", "modification du registre"),
    (r"icacls|takeown|runas|start-process.*-verb\s+runas", "changement de droits ou élévation"),
    (r"invoke-webrequest|iwr\b|curl\b|wget\b|invoke-restmethod", "accès réseau"),
    (r"invoke-expression|iex\b", "exécution de code dynamique"),
    (r"git\s+push", "publication vers un dépôt distant"),
    (
        r"git\s+(clean|reset\s+--hard|checkout\s+(--|\.)|restore|rm\b|branch\s+-d|stash\s+(drop|clear))",
        "commande git qui efface du travail",
    ),
    (
        r"pip\s+(install|uninstall)|npm\s+(install|i|uninstall)\s+-g|winget|choco|msiexec|scoop",
        "installation ou désinstallation de logiciel",
    ),
    (r"new-itemproperty|disable-|enable-.*firewall|netsh", "modification système ou réseau"),
]


def classer(action: Action) -> Verdict:
    if action.nom == "delete":
        return Verdict(True, "suppression définitive")
    if action.nom in ("run", "start"):
        return analyser_commande(action.champs.get("command", ""))
    return Verdict(False)


# Séparateurs de commandes enchaînées : chaque morceau est vérifié.
_SEPARATEURS = re.compile(r";|&&|\|\||\||&|\n")
# Redirections sans risque : erreurs vers la sortie, sortie jetée.
_REDIRECTIONS_SURES = re.compile(r"\d?>&\d|\d?>\s*(\$null|nul)\b")


def analyser_commande(texte: str) -> Verdict:
    bas = texte.strip().lower()
    for motif, raison in MOTIFS_DANGEREUX:
        if re.search(motif, bas):
            return Verdict(True, raison)
    nettoye = _REDIRECTIONS_SURES.sub("", bas)
    if ">" in nettoye:
        return Verdict(True, "écriture dans un fichier par redirection")
    for morceau in _SEPARATEURS.split(nettoye):
        morceau = morceau.strip()
        if not morceau:
            continue
        if morceau.split()[0] not in COMMANDES_SURES:
            return Verdict(True, "commande non reconnue")
    return Verdict(False)
