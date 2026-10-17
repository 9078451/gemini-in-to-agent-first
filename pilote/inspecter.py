"""Montre, pour chaque repère, combien d'éléments chaque candidat trouve.

Usage :
  python -m pilote.inspecter                   compte chaque candidat
  python -m pilote.inspecter --html "CSS"      affiche le HTML du 1er élément trouvé
  python -m pilote.inspecter --medias          médias (images, vidéos, sons) de la dernière réponse
"""
import argparse
import sys

import config
from pilote.chrome import ONGLET_COWORK, ChromeDedie, OngletGemini
from pilote.medias import LISTER_MEDIAS, etat_medias, parametres
from pilote.reperes import premier_present
from pilote.selecteurs import REPERES


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspecte la page Gemini du Chrome dédié.")
    parser.add_argument("--html", metavar="CSS", help="affiche le HTML du premier élément trouvé")
    parser.add_argument("--medias", action="store_true", help="médias de la dernière réponse")
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
        if args.medias:
            reponses = premier_present(page, "reponse")
            if reponses is None:
                print("Aucune réponse dans la page.")
                return
            derniere = reponses.last
            nombre, en_preparation = etat_medias(derniere)
            print(f"{nombre} média(s){' — un média est encore en préparation' if en_preparation else ''}")
            for m in derniere.evaluate(LISTER_MEDIAS, parametres()):
                print(f"  {m['type']:6} {m['url'][:110]}  {m['description'][:40]}")
            return
        for nom, candidats in REPERES.items():
            print(nom)
            for selecteur in candidats:
                print(f"  {page.locator(selecteur).count():>3}  {selecteur}")
    finally:
        onglet.fermer()


if __name__ == "__main__":
    main()
