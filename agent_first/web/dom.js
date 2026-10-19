// Petits outils DOM partagés par les modules de l'app.

export const $ = (id) => document.getElementById(id);

export function element(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

export function icone(nom) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${nom}`);
  svg.append(use);
  return svg;
}

export function boutonIcone(nom, titre, action) {
  const bouton = element("button", "icone");
  bouton.type = "button";
  bouton.title = titre;
  bouton.setAttribute("aria-label", titre);
  bouton.append(icone(nom));
  bouton.addEventListener("click", (e) => {
    e.stopPropagation();
    action(e);
  });
  return bouton;
}

export function lire(cle, defaut) {
  try {
    return JSON.parse(localStorage.getItem(cle)) ?? defaut;
  } catch {
    return defaut;
  }
}

export function ecrire(cle, valeur) {
  try {
    localStorage.setItem(cle, JSON.stringify(valeur));
  } catch {
    // stockage indisponible : la préférence ne sera simplement pas gardée
  }
}

// Notification discrète, en bas au centre ; `genre` : info, ok, attention, erreur.
const COULEURS = { ok: "pret", attention: "limite", erreur: "panne", info: "" };

// La zone est un « popover » : dans la couche du dessus, elle reste visible au-dessus d'une
// fenêtre ouverte (Paramètres). La remontrer la place au-dessus de la dernière ouverte.
function montrerZone(zone) {
  if (!zone.showPopover) return;
  if (zone.matches(":popover-open")) zone.hidePopover();
  zone.showPopover();
}

export function notifier(texte, genre = "info", duree = 3200) {
  const zone = $("notifications");
  const note = element("div", "notification");
  const point = element("span", `point ${COULEURS[genre] ?? ""}`);
  note.append(point, element("span", null, texte));
  zone.append(note);
  while (zone.children.length > 3) zone.firstElementChild.remove();
  montrerZone(zone);
  setTimeout(() => {
    note.classList.add("sortie");
    setTimeout(() => {
      note.remove();
      if (!zone.children.length && zone.matches?.(":popover-open")) zone.hidePopover();
    }, 220);
  }, duree);
}

export async function copier(texte, quoi = "Copié") {
  try {
    await navigator.clipboard.writeText(texte);
    notifier(quoi, "ok", 1800);
  } catch {
    notifier("Copie impossible", "erreur");
  }
}
