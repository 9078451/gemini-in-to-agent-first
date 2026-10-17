"""Montre, pour chaque repère, combien d'éléments chaque candidat trouve.

Usage :
  python -m pilote.inspecter                   compte chaque candidat
  python -m pilote.inspecter --html "CSS"      affiche le HTML du 1er élément trouvé
"""
import argparse
import sys

import config
from pilote.chrome import ONGLET_COWORK, ChromeDedie, OngletGemini
from pilote.selecteurs import REPERES


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspecte la page Gemini du Chrome dédié.")
    parser.add_argument("--html", metavar="CSS", help="affiche le HTML du premier élément trouvé")
    args = parser.parse_args()

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    onglet = OngletGemini(chrome, ONGLET_COWORK, principal=True)
    try:
        page = onglet.page()
        print(f"Page : {page.url}\n")
        if args.html:
            elements = page.locator(args.html)
            if elements.count() == 0:
                print("Aucun élément trouvé.")
            else:
                print(elements.first.evaluate("e => e.outerHTML")[:4000])
            return
        for nom, candidats in REPERES.items():
            print(nom)
            for selecteur in candidats:
                print(f"  {page.locator(selecteur).count():>3}  {selecteur}")
    finally:
        onglet.fermer()


if __name__ == "__main__":
    main()
