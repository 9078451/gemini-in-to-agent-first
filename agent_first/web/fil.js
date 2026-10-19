// Le fil d'une conversation : bulles, réponses (HTML nettoyé), blocs de code, défilement.
import { $, boutonIcone, copier, element } from "./dom.js";
import { noms } from "./etat.js";
import { metaMessage, texteSecours } from "./outils.js";

// ---- défilement : le fil suit la réponse seulement si on est déjà en bas ----

export function estEnBas() {
  const fil = $("fil");
  return fil.scrollHeight - fil.scrollTop - fil.clientHeight < 48;
}

export function defilerEnBas(forcer = false) {
  const fil = $("fil");
  if (forcer || estEnBas()) fil.scrollTop = fil.scrollHeight;
  majBoutonBas();
}

export function majBoutonBas() {
  $("revenir-bas").hidden = estEnBas();
}

export function brancherDefilement() {
  const fil = $("fil");
  fil.addEventListener("scroll", majBoutonBas, { passive: true });
  $("revenir-bas").addEventListener("click", () => {
    fil.scrollTo({ top: fil.scrollHeight, behavior: "smooth" });
  });
  new ResizeObserver(majBoutonBas).observe(fil);
}

// ---- réponses ----

// Les blocs de code reçoivent un en-tête : la langue et un bouton Copier.
export function preparerMarkdown(conteneur) {
  for (const pre of conteneur.querySelectorAll("pre")) {
    if (pre.parentElement?.classList.contains("bloc-code")) continue;
    const bloc = element("div", "bloc-code");
    const entete = element("div", "bloc-code-entete", pre.dataset.langue || "code");
    entete.append(boutonIcone("i-copier", "Copier le code", () => copier(pre.innerText, "Code copié")));
    pre.replaceWith(bloc);
    bloc.append(entete, pre);
  }
  for (const lien of conteneur.querySelectorAll("a[href]")) {
    lien.target = "_blank";
    lien.rel = "noopener noreferrer";
  }
}

export function remplirReponse(contenu, message) {
  if (message.html) {
    contenu.innerHTML = message.html; // déjà nettoyé par Agent First (nh3)
    preparerMarkdown(contenu);
  } else {
    contenu.textContent = message.texte;
  }
}

export function bulle(message, reessayer) {
  if (message.role === "toi") {
    const b = element("div", "bulle toi");
    b.append(element("div", "texte-toi", message.texte));
    return b;
  }
  if (message.role === "erreur") {
    const b = element("div", "bulle erreur", message.texte);
    if (reessayer) {
      const bouton = element("button", "bouton-secondaire", "Réessayer");
      bouton.type = "button";
      bouton.addEventListener("click", () => {
        b.remove();
        reessayer();
      });
      b.append(element("br"), bouton);
    }
    return b;
  }
  // Réponse : du texte, sans carte ; le fournisseur, le modèle et la durée en dessous, en petit.
  const carte = element("article", "bulle reponse");
  const contenu = element("div", "markdown");
  remplirReponse(contenu, message);
  const pied = element("div", "message-pied");
  pied.append(element("span", "point"), element("span", null, metaMessage(message, noms())));
  const secours = texteSecours(message, noms());
  if (secours) pied.append(element("span", "secours", `· ${secours}`));
  pied.append(boutonIcone("i-copier", "Copier la réponse", () => copier(message.texte, "Réponse copiée")));
  carte.append(contenu, pied);
  return carte;
}

// Réponse en cours d'écriture : même contenu que la réponse finale, avec un curseur.
export function bulleEnEcriture() {
  const carte = element("article", "bulle reponse en-ecriture");
  const contenu = element("div", "markdown");
  carte.append(contenu);
  return {
    carte,
    afficher(texte, html) {
      if (html) {
        contenu.innerHTML = html; // nettoyé par Agent First (nh3)
        preparerMarkdown(contenu);
      } else {
        contenu.textContent = texte;
      }
    },
  };
}

export function bulleAttente(texte) {
  const attente = element("div", "bulle attente");
  const libelle = element("span", null, texte);
  attente.append(element("span", "points"), libelle);
  return { attente, libelle };
}
