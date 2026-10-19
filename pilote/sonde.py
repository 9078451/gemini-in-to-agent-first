"""Lire l'état d'une page de chat en un seul aller-retour avec Chrome.

Avant, chaque vérification (toutes les 0,3 à 0,5 s) comptait les questions, les
réponses, cherchait le bouton « Arrêter » puis lisait le texte : 4 à 6 appels à
Chrome, chacun essayant plusieurs sélecteurs. La sonde fait tout dans un seul
`page.evaluate` et garde le résultat un court instant : les vérifications d'un même
tour de boucle (compter, génération en cours, texte) le partagent.
"""
import time
from typing import Callable

SONDER = r"""(a) => {
  const premiers = (candidats) => {
    for (const s of candidats || []) {
      const e = document.querySelectorAll(s);
      if (e.length) return e;
    }
    return [];
  };
  const visible = (e) => {
    if (!e) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
  };
  const reponses = premiers(a.reperes.reponse);
  const arreter = premiers(a.reperes.generation);
  const bandeau = premiers(a.reperes.limite);
  const n = a.indice === null || a.indice === undefined ? reponses.length - 1 : a.indice;
  const r = n >= 0 && n < reponses.length ? reponses[n] : null;
  // Texte d'une copie détachée (innerText n'y marche pas) : un retour à la ligne par bloc.
  const BLOCS = /^(P|DIV|LI|PRE|H[1-6]|TR|UL|OL|TABLE|BLOCKQUOTE|SECTION|ARTICLE|HR)$/;
  const texteDe = (noeud) => {
    if (noeud.nodeType === 3) return noeud.nodeValue;
    if (noeud.nodeType !== 1) return '';
    if (noeud.tagName === 'BR') return '\n';
    if (noeud.tagName === 'PRE') return '\n' + noeud.textContent + '\n';
    const interieur = [...noeud.childNodes].map(texteDe).join('');
    if (noeud.tagName === 'TD' || noeud.tagName === 'TH') return interieur + '\t';
    return BLOCS.test(noeud.tagName) ? '\n' + interieur + '\n' : interieur;
  };
  let html = '';
  let copie = null;
  if (r && a.html) {
    copie = (r.querySelector(a.html.contenu) || r).cloneNode(true);
    copie.querySelectorAll(a.html.code).forEach(bloc => {
      const entete = bloc.querySelector(a.html.entete);
      const langue = entete ? entete.innerText.trim().split('\n')[0].trim() : '';
      const pre = bloc.querySelector('pre');
      if (pre && langue) pre.setAttribute('data-langue', langue);
    });
    copie.querySelectorAll(a.html.decor).forEach(e => e.remove());
    html = copie.innerHTML;
  }
  let texte = '';
  if (r) {
    // Sites : le texte du contenu nettoyé (sans les boutons « Copier »…) ; Gemini : la page telle quelle.
    texte = copie && a.html.texte_contenu
      ? texteDe(copie).replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()
      : r.innerText;
  }
  return {
    questions: premiers(a.reperes.question).length,
    reponses: reponses.length,
    generation: arreter.length > 0 && visible(arreter[0]),
    limite: bandeau.length && visible(bandeau[0]) ? (bandeau[0].innerText.replace(/\s+/g, ' ').trim() || null) : null,
    texte,
    html,
  };
}"""

VIDE = {"questions": 0, "reponses": 0, "generation": False, "limite": None, "texte": "", "html": ""}


class Sonde:
    """`reperes` : candidats CSS de « question », « reponse », « generation » (bouton Arrêter
    ou marque d'écriture) et « limite » (bandeau). `html` : sélecteurs pour extraire le HTML
    de la réponse (contenu, code, entete, decor), ou None. `indice` : la réponse à lire
    (None = la dernière)."""

    def __init__(
        self,
        page,
        reperes: dict[str, list[str]],
        html: dict[str, str] | None = None,
        indice: int | None = None,
        fraicheur: float = 0.05,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._page = page
        self._arguments = {"reperes": reperes, "html": html, "indice": indice}
        self._fraicheur = fraicheur
        self._horloge = horloge
        self._derniere: dict | None = None
        self._quand = 0.0

    def viser(self, indice: int | None) -> None:
        """Lit désormais la réponse n° `indice` (la nouvelle réponse attendue)."""
        self._arguments["indice"] = indice
        self._derniere = None

    def lire(self) -> dict:
        maintenant = self._horloge()
        if self._derniere is None or maintenant - self._quand > self._fraicheur:
            self._derniere = {**VIDE, **(self._page.evaluate(SONDER, self._arguments) or {})}
            self._quand = maintenant
        return self._derniere

    # raccourcis pour les fonctions d'attente
    def questions(self) -> int:
        return self.lire()["questions"]

    def reponses(self) -> int:
        return self.lire()["reponses"]

    def generation(self) -> bool:
        return self.lire()["generation"]

    def limite(self) -> str | None:
        return self.lire()["limite"]

    def texte(self) -> str:
        return self.lire()["texte"]

    def html(self) -> str:
        return self.lire()["html"]
