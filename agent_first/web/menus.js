// Réglages de la zone de saisie : un seul menu des modèles, rangé par fournisseur (avec son
// état et l'interrupteur du secours), et le menu du niveau de réflexion.
import { appeler } from "./api.js";
import { $, element, icone, notifier } from "./dom.js";
import { etat, fournisseur } from "./etat.js";
import { choixDisponible, libelleEtat, limiteOption } from "./outils.js";

const MENUS = { "bouton-modele": "menu-modeles", "bouton-niveau": "menu-niveaux" };
let rappels = { ouvrirParametres: () => {}, changement: () => {} };

export function brancherMenus(r) {
  rappels = r;
  $("bouton-modele").addEventListener("click", () => basculerMenu("bouton-modele"));
  $("bouton-niveau").addEventListener("click", () => basculerMenu("bouton-niveau"));
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".menu-reglage")) fermerMenus();
  });
}

export function basculerMenu(bouton) {
  const ouvrir = $(MENUS[bouton]).hidden;
  fermerMenus();
  if (!ouvrir) return;
  dessinerMenus();
  $(MENUS[bouton]).hidden = false;
  $(bouton).setAttribute("aria-expanded", "true");
  $(MENUS[bouton]).querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
}

export function fermerMenus() {
  for (const [bouton, menu] of Object.entries(MENUS)) {
    $(menu).hidden = true;
    $(bouton).setAttribute("aria-expanded", "false");
  }
}

export function menusOuverts() {
  return Object.values(MENUS).some((menu) => !$(menu).hidden);
}

function option(o, choisi, choisir) {
  const bouton = element("button", "option");
  bouton.type = "button";
  bouton.setAttribute("role", "option");
  bouton.setAttribute("aria-selected", String(choisi));
  bouton.append(element("span", "option-nom", o.nom));
  const limite = limiteOption(o);
  if (limite) {
    bouton.classList.add("bloquee"); // le site refusera ce choix jusqu'à la réinitialisation
    bouton.title = `Bloqué par la limite de ton compte jusqu'au ${limite}`;
    bouton.append(element("span", "option-desc", `jusqu'au ${limite}`));
  } else if (o.description) {
    bouton.append(element("span", "option-desc", o.description));
  }
  bouton.addEventListener("click", () => {
    choisir();
    fermerMenus();
    dessinerMenus();
    rappels.changement();
  });
  return bouton;
}

function groupe(f) {
  const titre = element("div", "menu-groupe");
  titre.append(element("span", `point ${f.etat}`), element("span", null, f.type === "web" ? `${f.nom} · site` : f.nom));
  const libelle = libelleEtat(f.etat, f.detail);
  if (libelle) titre.append(element("span", `detail ${f.etat}`, libelle));
  return titre;
}

function piedSecours() {
  const pied = element("div", "menu-pied");
  const interrupteur = element("button", "interrupteur");
  interrupteur.type = "button";
  interrupteur.setAttribute("role", "switch");
  interrupteur.setAttribute("aria-checked", String(!!etat.secours.actif));
  interrupteur.setAttribute("aria-label", "Secours si limite ou panne");
  interrupteur.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!etat.secours.fournisseur) {
      fermerMenus();
      notifier("Choisis d'abord le fournisseur de secours", "attention");
      rappels.ouvrirParametres("general");
      return;
    }
    try {
      const r = await appeler("PUT", "/api/secours", { ...etat.secours, actif: !etat.secours.actif });
      etat.secours = r.secours;
      dessinerMenus();
      notifier(etat.secours.actif ? "Secours activé" : "Secours désactivé", "ok");
    } catch (erreur) {
      notifier(erreur.message, "erreur");
    }
  });
  const gerer = element("button", "lien", "Gérer");
  gerer.type = "button";
  gerer.addEventListener("click", () => {
    fermerMenus();
    rappels.ouvrirParametres("fournisseurs");
  });
  pied.append(icone("i-relais"), element("span", null, "Secours si limite ou panne"), interrupteur, gerer);
  pied.title = etat.secours.fournisseur
    ? `Secours : ${fournisseur(etat.secours.fournisseur)?.nom ?? etat.secours.fournisseur}${etat.secours.modele ? ` · ${etat.secours.modele}` : ""}`
    : "Aucun fournisseur de secours choisi";
  return pied;
}

export function dessinerMenus() {
  const { choix } = etat;
  const actuel = fournisseur(choix.fournisseur);
  $("nom-modele").textContent = actuel
    ? (choix.modele && choix.modele !== "Par défaut" ? choix.modele : actuel.nom)
    : "Modèle";
  $("bouton-modele").title = actuel ? `${actuel.nom}${choix.modele ? ` · ${choix.modele}` : ""}` : "Fournisseur et modèle";
  $("point-modele").className = `point ${actuel?.etat ?? ""}`;
  $("nom-niveau").textContent = choix.niveau ? `Réflexion ${choix.niveau}` : "Réflexion";
  $("bouton-niveau").parentElement.hidden = !actuel?.niveaux.length;

  const contenu = [];
  for (const f of etat.fournisseurs) {
    contenu.push(groupe(f));
    if (!f.modeles.length) {
      const vide = element("button", "option");
      vide.type = "button";
      vide.append(element("span", "option-desc", "Choisir des modèles…"));
      vide.addEventListener("click", () => {
        fermerMenus();
        rappels.ouvrirParametres("fournisseurs", f.id);
      });
      contenu.push(vide);
    }
    for (const o of f.modeles) {
      contenu.push(option(o, f.id === choix.fournisseur && o.nom === choix.modele, () => {
        const niveau = f.niveaux.length ? choixDisponible(f.niveaux, choix.niveau) : null;
        etat.choix = { fournisseur: f.id, modele: o.nom, niveau };
      }));
    }
  }
  contenu.push(piedSecours());
  $("menu-modeles").replaceChildren(...contenu);
  $("menu-niveaux").replaceChildren(
    ...(actuel?.niveaux ?? []).map((o) => option(o, o.nom === choix.niveau, () => {
      etat.choix = { ...etat.choix, niveau: o.nom };
    })),
  );
}
