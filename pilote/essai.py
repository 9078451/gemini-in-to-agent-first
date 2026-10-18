"""Essai réel : envoie un message à Gemini et affiche la réponse.

Usage :
  python -m pilote.essai "Bonjour"                     nouvelle conversation
  python -m pilote.essai "Et ensuite ?" --suite URL    continue la conversation URL
  python -m pilote.essai "Bonjour" --modele "3.1 Pro" --niveau Max. --html
  python -m pilote.essai "Un chat roux sur un toit" --outil image    médias dans journaux/essai-*
  python -m pilote.essai "Mets le ciel en violet" --outil image --joindre photo.jpg
  python -m pilote.essai "Bonjour" --site chatgpt                      un autre site (claude, mistral…)
Dans le texte, \\n devient un retour à la ligne.
"""
import argparse
import mimetypes
import sys
from datetime import datetime
from pathlib import Path

import config
from pilote.chrome import ONGLET_COWORK, ChromeDedie, OngletGemini
from pilote.erreurs import ErreurPilote
from pilote.gemini import PiloteGemini
from pilote.medias import extension
from pilote.modeles import OUTILS, Media
from pilote.sites import GEMINI, SITES


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Envoie un message à Gemini web.")
    parser.add_argument("texte")
    parser.add_argument("--suite", metavar="URL", help="adresse d'une conversation Gemini à continuer")
    parser.add_argument("--modele", help="ex. « 3.1 Pro »")
    parser.add_argument("--niveau", help="Min., Moyen ou Max.")
    parser.add_argument("--html", action="store_true", help="affiche aussi le HTML de la réponse")
    parser.add_argument("--outil", choices=OUTILS, help="coche l'outil de création de Gemini")
    parser.add_argument("--delai", type=float, help="limite de temps de la réponse, en secondes")
    parser.add_argument("--joindre", metavar="FICHIER", action="append", default=[], help="fichier joint (répétable)")
    parser.add_argument("--site", choices=list(SITES), default="gemini", help="assistant à piloter")
    args = parser.parse_args()
    site = SITES[args.site]
    pieces = []
    for chemin in map(Path, args.joindre):
        mime = mimetypes.guess_type(chemin.name)[0] or "application/octet-stream"
        pieces.append(Media(mime.split("/")[0] if mime.split("/")[0] in ("image", "video", "audio") else "fichier",
                            mime, chemin.read_bytes(), chemin.name))

    chrome = ChromeDedie(config.CHEMIN_CHROME, config.DOSSIER_PROFIL, config.PORT_CHROME, config.URL_GEMINI)
    if site is GEMINI:
        onglet = OngletGemini(chrome, ONGLET_COWORK, principal=True)
    else:
        onglet = OngletGemini(chrome, site.nom, principal=True, prefixe=site.prefixe, url=site.url)
    pilote = PiloteGemini(
        onglet, site.url if site is not GEMINI else config.URL_GEMINI, config.DELAI_REPONSE, config.STABILITE,
        config.DOSSIER_JOURNAUX, site=site,
    )
    try:
        resultat = pilote.envoyer(
            args.suite, args.texte.replace("\\n", "\n"), args.modele, args.niveau, delai=args.delai, outil=args.outil,
            pieces=tuple(pieces), au_fil=lambda texte: print(f"\r… {len(texte)} caractères", end="", file=sys.stderr),
        )
        print(file=sys.stderr)
    except ErreurPilote as e:
        print(f"ERREUR : {e}", file=sys.stderr)
        return 1
    finally:
        onglet.fermer()
    print(resultat.reponse)
    if args.html:
        print("\n--- HTML ---\n" + resultat.html)
    for i, media in enumerate(resultat.medias, 1):
        config.DOSSIER_JOURNAUX.mkdir(parents=True, exist_ok=True)
        chemin = config.DOSSIER_JOURNAUX / f"essai-{datetime.now():%Y%m%d-%H%M%S}-{i}.{extension(media.mime)}"
        chemin.write_bytes(media.donnees)
        print(f"[{media.type} {media.mime}, {len(media.donnees) // 1024} Ko : {chemin}]")
    if resultat.medias_perdus:
        print(f"[{resultat.medias_perdus} média(s) vu(s) mais non téléchargé(s) : voir le journal]")
    print(
        f"\n[conversation : {resultat.adresse} · modèle : {resultat.modele or '?'}"
        f" · niveau : {resultat.niveau or '?'} · {resultat.duree} s]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
