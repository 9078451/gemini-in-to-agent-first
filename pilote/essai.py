"""Essai réel : envoie un message à Gemini et affiche la réponse.

Usage :
  python -m pilote.essai "Bonjour"                     nouvelle conversation
  python -m pilote.essai "Et ensuite ?" --suite URL    continue la conversation URL
Dans le texte, \\n devient un retour à la ligne.
"""
import argparse
import sys

import config
from pilote.chrome import ChromeDedie
from pilote.erreurs import ErreurPilote
from pilote.gemini import PiloteGemini


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Envoie un message à Gemini web.")
    parser.add_argument("texte")
    parser.add_argument("--suite", metavar="URL", help="adresse d'une conversation Gemini à continuer")
    args = parser.parse_args()

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    pilote = PiloteGemini(
        chrome, config.URL_GEMINI, config.DELAI_REPONSE, config.STABILITE, config.DOSSIER_JOURNAUX
    )
    try:
        resultat = pilote.envoyer(args.suite, args.texte.replace("\\n", "\n"))
    except ErreurPilote as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        return 1
    finally:
        chrome.fermer()
    print(resultat.reponse)
    print(f"\n[conversation : {resultat.adresse}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
