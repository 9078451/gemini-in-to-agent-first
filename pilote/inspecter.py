"""Montre, pour chaque repère d'un site, combien d'éléments chaque candidat trouve.

Usage :
  python -m pilote.inspecter                       Gemini : compte chaque candidat
  python -m pilote.inspecter --site chatgpt        ChatGPT (ou claude_web)
  python -m pilote.inspecter --html "CSS"          affiche le HTML du 1er élément trouvé
Le site doit être ouvert dans le Chrome dédié (Paramètres → Fournisseurs → Ouvrir).
"""
import argparse
import sys

import config
from pilote.chrome import ONGLET_CHAT, ONGLET_COWORK, ChromeDedie, OngletGemini, OngletSite
from pilote.selecteurs import REPERES
from pilote.sites import PROFILS


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspecte la page d'un site dans le Chrome dédié.")
    parser.add_argument("--site", choices=["gemini", *PROFILS], default="gemini")
    parser.add_argument("--html", metavar="CSS", help="affiche le HTML du premier élément trouvé")
    args = parser.parse_args()

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    if args.site == "gemini":
        onglet, reperes = OngletGemini(chrome, ONGLET_COWORK, principal=True), REPERES
    else:
        profil = PROFILS[args.site]
        onglet = OngletSite(chrome, ONGLET_CHAT, principal=True, url_accueil=profil.url_nouvelle, prefixe=profil.prefixe)
        reperes = profil.reperes
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
        for nom, candidats in reperes.items():
            print(nom)
            for selecteur in candidats:
                print(f"  {page.locator(selecteur).count():>3}  {selecteur}")
    finally:
        onglet.fermer()


if __name__ == "__main__":
    main()
