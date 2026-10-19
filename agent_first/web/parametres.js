// Paramètres, en onglets : Général (choix par défaut, secours), Fournisseurs (activer, clés,
// modèles, sites à ouvrir), API réseau, État.
import { appeler } from "./api.js";
import { $, boutonIcone, copier, element, ecrire, icone, lire, notifier } from "./dom.js";
import { etat, nom } from "./etat.js";
import { choixValide, libelleEtat } from "./outils.js";

export const CLE_DEFAUT = "agent.first.defaut";
const AVERTISSEMENT_SITES = "ChatGPT et Claude.ai interdisent l'usage automatisé dans leurs conditions : "
  + "ton compte peut être limité ou suspendu. Les clés API sont la voie stable.";

let rappels = { rafraichir: async () => {}, changementDefaut: () => {} };
let ouvert = null; // fournisseur déplié dans l'onglet Fournisseurs

export function brancherParametres(r) {
  rappels = r;
  $("fermer-parametres").addEventListener("click", () => $("parametres").close());
  $("parametres").addEventListener("click", (e) => {
    if (e.target === $("parametres")) $("parametres").close(); // clic sur le fond
  });
  $("onglets").addEventListener("click", (e) => {
    const bouton = e.target.closest("[data-onglet]");
    if (bouton) afficherOnglet(bouton.dataset.onglet);
  });
}

export function choixParDefaut() {
  const brut = lire(CLE_DEFAUT, {});
  return choixValide(etat.fournisseurs, { fournisseur: brut.fournisseur ?? "gemini", modele: brut.modele, niveau: brut.niveau });
}

export function ouvrirParametres(onglet = "general", deplier = null) {
  if (deplier) ouvert = deplier;
  afficherOnglet(onglet);
  if (!$("parametres").open) $("parametres").showModal();
}

function afficherOnglet(onglet) {
  $("onglets").querySelectorAll("button").forEach((b) => b.classList.toggle("actif", b.dataset.onglet === onglet));
  const zone = $("onglet-contenu");
  zone.dataset.onglet = onglet;
  ({ general: ongletGeneral, fournisseurs: ongletFournisseurs, api: ongletApi, etat: ongletEtat })[onglet](zone);
}

function rafraichirOnglet() {
  const zone = $("onglet-contenu");
  if ($("parametres").open && zone.dataset.onglet) afficherOnglet(zone.dataset.onglet);
}

function section(titre, ...enfants) {
  const s = element("section", "section");
  if (titre) s.append(element("h3", null, titre));
  s.append(...enfants);
  return s;
}

function champ(libelle, controle) {
  const l = element("label", "champ");
  l.append(element("span", null, libelle), controle);
  return l;
}

function bouton(texte, action, classe = "bouton-secondaire") {
  const b = element("button", classe, texte);
  b.type = "button";
  b.addEventListener("click", action);
  return b;
}

function interrupteur(actif, libelle, changer, desactive = false) {
  const b = element("button", "interrupteur");
  b.type = "button";
  b.setAttribute("role", "switch");
  b.setAttribute("aria-checked", String(actif));
  b.setAttribute("aria-label", libelle);
  b.disabled = desactive;
  if (desactive) b.title = "Toujours actif";
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    changer(!actif);
  });
  return b;
}

// Liste déroulante « fournisseur · modèle » rangée par fournisseur actif.
function selectModeles(valeur, avecAucun = false) {
  const select = element("select");
  if (avecAucun) select.append(new Option("Aucun", ""));
  for (const f of etat.fournisseurs) {
    const groupe = element("optgroup");
    groupe.label = f.nom;
    for (const m of f.modeles) {
      groupe.append(new Option(m.nom, `${f.id}|${m.nom}`, false, valeur === `${f.id}|${m.nom}`));
    }
    if (f.modeles.length) select.append(groupe);
  }
  return select;
}

// ---- Général ------------------------------------------------------------

function ongletGeneral(zone) {
  const defaut = choixParDefaut();
  const modele = selectModeles(`${defaut.fournisseur}|${defaut.modele}`);
  const niveau = element("select");
  const remplirNiveaux = () => {
    const [id] = modele.value.split("|");
    const f = etat.fournisseurs.find((x) => x.id === id);
    niveau.replaceChildren(...(f?.niveaux ?? []).map((n) => new Option(`${n.nom}${n.description ? ` — ${n.description}` : ""}`, n.nom, false, n.nom === defaut.niveau)));
    niveau.parentElement && (niveau.parentElement.hidden = !f?.niveaux.length);
  };
  const sauver = () => {
    const [fournisseur, ...reste] = modele.value.split("|");
    ecrire(CLE_DEFAUT, { fournisseur, modele: reste.join("|"), niveau: niveau.value || null });
    rappels.changementDefaut();
    notifier("Choix par défaut enregistré", "ok");
  };
  modele.addEventListener("change", () => {
    remplirNiveaux();
    sauver();
  });
  niveau.addEventListener("change", sauver);
  const champNiveau = champ("Niveau de réflexion", niveau);
  const rangee = element("div", "rangee");
  rangee.append(champ("Fournisseur et modèle", modele), champNiveau);

  const s = etat.secours;
  const secours = selectModeles(s.fournisseur ? `${s.fournisseur}|${s.modele}` : "", true);
  const regler = async (actif) => {
    const [fournisseur, ...reste] = secours.value.split("|");
    try {
      const r = await appeler("PUT", "/api/secours", { actif: actif && !!fournisseur, fournisseur: fournisseur || null, modele: reste.join("|") || null });
      etat.secours = r.secours;
      notifier(etat.secours.actif ? `Secours : ${nom(etat.secours.fournisseur)}` : "Secours désactivé", "ok");
      ongletGeneral(zone);
    } catch (e) {
      notifier(e.message, "erreur");
    }
  };
  secours.addEventListener("change", () => regler(!!secours.value));
  const ligneSecours = element("div", "champ-ligne");
  ligneSecours.append(interrupteur(!!s.actif, "Secours actif", regler), element("span", null, s.actif ? "Activé" : "Désactivé"));

  zone.replaceChildren(
    section("Nouvelles conversations", rangee, element("p", "note", "Gardé dans ce navigateur. Chaque conversation garde ensuite son propre choix.")),
    section("Secours si limite ou panne", ligneSecours, champ("Fournisseur de secours", secours),
      element("p", "note", "Si le fournisseur d'une conversation atteint sa limite ou ne répond plus, le message repart chez celui-ci, avec l'historique. La conversation y continue.")),
  );
  remplirNiveaux();
}

// ---- Fournisseurs ---------------------------------------------------------

async function enregistrer(id, changements, message = "Enregistré") {
  try {
    const r = await appeler("PUT", `/api/fournisseurs/${id}`, changements);
    etat.tous = r.tous;
    etat.secours = r.secours;
    await rappels.rafraichir();
    notifier(message, "ok");
    rafraichirOnglet();
  } catch (e) {
    notifier(e.message, "erreur");
  }
}

function resumeFournisseur(f) {
  if (!f.actif) return "inactif";
  const actif = etat.fournisseurs.find((x) => x.id === f.id);
  const etatTexte = actif ? libelleEtat(actif.etat, actif.detail) : "";
  if (f.type === "api" && f.cle_requise && !f.cle) return "clé manquante";
  return etatTexte || (f.cle ? `clé ${f.cle}` : "actif");
}

function corpsApi(f) {
  const corps = [];
  if (f.cle_requise || f.id === "perso") {
    const cle = element("input");
    cle.type = "password";
    cle.autocomplete = "off";
    cle.placeholder = f.cle ? `Clé enregistrée (${f.cle}) — colle une autre clé pour la changer` : "Colle ta clé API";
    const ligne = element("div", "champ-ligne");
    ligne.append(cle, bouton("Enregistrer", () => {
      if (!cle.value.trim()) return notifier("La clé est vide", "attention");
      enregistrer(f.id, { cle: cle.value.trim(), actif: true }, "Clé enregistrée");
    }));
    if (f.cle) ligne.append(bouton("Effacer", () => enregistrer(f.id, { cle: "" }, "Clé effacée")));
    corps.push(champ("Clé API", ligne));
  }
  if (f.url_modifiable) {
    const url = element("input");
    url.type = "url";
    url.value = f.url;
    const ligne = element("div", "champ-ligne");
    ligne.append(url, bouton("Enregistrer", () => enregistrer(f.id, { url: url.value }, "Adresse enregistrée")));
    corps.push(champ("Adresse du serveur", ligne));
  }
  const choix = element("div", "modeles-choix");
  // Ceux du menu en ce moment : choisis, sinon lus chez le fournisseur ou suggérés.
  const affiches = etat.fournisseurs.find((x) => x.id === f.id)?.modeles.map((m) => m.nom) ?? [];
  const afficherCases = (liste) => {
    const coches = new Set(f.modeles.length ? f.modeles : affiches.length ? affiches : liste.slice(0, 8));
    choix.replaceChildren(...liste.map((m) => {
      const l = element("label", "modele-case");
      const c = element("input");
      c.type = "checkbox";
      c.value = m;
      c.checked = coches.has(m);
      l.append(c, document.createTextNode(m));
      return l;
    }));
  };
  afficherCases(f.modeles.length ? f.modeles : affiches);
  const lireListe = bouton("Lire la liste", async () => {
    if (!f.actif) return notifier("Active d'abord ce fournisseur", "attention");
    lireListe.disabled = true;
    try {
      const { modeles } = await appeler("POST", `/api/fournisseurs/${f.id}/modeles`);
      afficherCases([...new Set([...f.modeles, ...affiches, ...modeles])]);
      notifier(`${modeles.length} modèles trouvés`, "ok");
    } catch (e) {
      notifier(e.message, "erreur", 6000);
    } finally {
      lireListe.disabled = false;
    }
  });
  const garder = bouton("Afficher ceux-ci", () => {
    const modeles = [...choix.querySelectorAll("input:checked")].map((c) => c.value);
    enregistrer(f.id, { modeles }, "Modèles enregistrés");
  });
  const actions = element("div", "champ-ligne");
  actions.append(lireListe, garder);
  corps.push(champ("Modèles affichés dans le menu", choix), actions);
  return corps;
}

function corpsSite(f) {
  const corps = [];
  if (f.id !== "gemini") corps.push(element("p", "note alerte", AVERTISSEMENT_SITES));
  const ouvrir = bouton("Ouvrir dans le Chrome dédié", async () => {
    if (!f.actif) return notifier("Active d'abord ce fournisseur", "attention");
    try {
      await appeler("POST", `/api/fournisseurs/${f.id}/ouvrir`);
      notifier(`${f.nom} s'ouvre dans le Chrome dédié : connecte-toi si besoin`, "ok", 5000);
    } catch (e) {
      notifier(e.message, "erreur");
    }
  });
  ouvrir.prepend(icone("i-externe"));
  corps.push(ouvrir);
  if (f.id === "chatgpt") {
    const modeles = element("input");
    modeles.type = "text";
    modeles.value = f.modeles.join(", ");
    modeles.placeholder = "Vide : le modèle choisi sur le site";
    const ligne = element("div", "champ-ligne");
    ligne.append(modeles, bouton("Enregistrer", () => enregistrer(f.id, { modeles: modeles.value.split(",") }, "Modèles enregistrés")));
    corps.push(champ("Modèles (noms courts de ChatGPT, séparés par des virgules)", ligne));
  }
  return corps;
}

function carteFournisseur(f) {
  const carte = element("div", "fournisseur");
  // Pas un <button> : il contient l'interrupteur (un bouton dans un bouton est interdit).
  const entete = element("div", "fournisseur-entete");
  entete.tabIndex = 0;
  entete.setAttribute("role", "button");
  entete.setAttribute("aria-expanded", String(ouvert === f.id));
  entete.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      entete.click();
    }
  });
  const actif = etat.fournisseurs.find((x) => x.id === f.id);
  entete.append(
    element("span", `point ${f.actif ? actif?.etat ?? "" : ""}`),
    element("span", "nom", f.nom),
    element("span", "type", f.type === "web" ? "site" : "API"),
    element("span", "resume", resumeFournisseur(f)),
    interrupteur(f.actif, `Activer ${f.nom}`, (valeur) => enregistrer(f.id, { actif: valeur }, valeur ? `${f.nom} activé` : `${f.nom} désactivé`), f.id === "gemini"),
  );
  entete.addEventListener("click", () => {
    ouvert = ouvert === f.id ? null : f.id;
    rafraichirOnglet();
  });
  carte.append(entete);
  if (ouvert === f.id) {
    const corps = element("div", "fournisseur-corps");
    corps.append(element("p", "note", f.aide), ...(f.type === "web" ? corpsSite(f) : corpsApi(f)));
    carte.append(corps);
  }
  return carte;
}

function ongletFournisseurs(zone) {
  const sites = etat.tous.filter((f) => f.type === "web");
  const api = etat.tous.filter((f) => f.type === "api");
  const liste = (fs) => {
    const conteneur = element("div");
    conteneur.append(...fs.map(carteFournisseur));
    return conteneur;
  };
  zone.replaceChildren(
    section("Sites, avec ton compte", element("p", "note", "Pilotés dans le Chrome dédié, comme Gemini. Ouvre le site une fois pour t'y connecter."), liste(sites)),
    section("API, avec une clé", element("p", "note", "Plus rapides et plus stables. Les clés restent sur ce PC (donnees/fournisseurs.json) et ne sont jamais réaffichées en entier."), liste(api)),
  );
}

// ---- API réseau -------------------------------------------------------------

function ligneApi(libelle, affiche, aCopier) {
  const ligne = element("div", "ligne-api");
  ligne.append(element("span", "ligne-api-nom", libelle), element("code", null, affiche),
    boutonIcone("i-copier", `Copier : ${libelle.toLowerCase()}`, () => copier(aCopier, `${libelle} copiée`)));
  return ligne;
}

async function ongletApi(zone) {
  zone.replaceChildren(element("p", "note", "Chargement…"));
  let infos;
  try {
    infos = await appeler("GET", "/api/api-reseau");
  } catch (e) {
    zone.replaceChildren(element("p", "note", e.message));
    return;
  }
  if (!infos.active) {
    zone.replaceChildren(section("API réseau", element("p", "note", "Désactivée. Pour l'activer : API_ACTIVE = True dans config.py, puis redémarre Agent First.")));
    return;
  }
  const regenerer = bouton("Régénérer la clé", async () => {
    if (!confirm("Créer une nouvelle clé ?\nLes programmes qui utilisent l'ancienne devront être mis à jour.")) return;
    try {
      await appeler("POST", "/api/api-reseau/cle");
      notifier("Nouvelle clé créée", "ok");
      ongletApi(zone);
    } catch (e) {
      notifier(e.message, "erreur");
    }
  });
  const exemple = element("p", "note");
  exemple.append("Format OpenAI (/v1/chat/completions, stream compris) et tâches Cowork (/v1/cowork), avec l'en-tête Authorization: Bearer <clé>. ",
    "Modèle : un nom de Gemini, ou « fournisseur/modèle » (ex. anthropic/claude-opus-5-5, ollama/llama3.2). Exemples dans le README.");
  zone.replaceChildren(section("API réseau", ligneApi("Adresse", infos.adresse, infos.adresse),
    ligneApi("Clé", `••••••••${infos.cle.slice(-4)}`, infos.cle), exemple, regenerer));
}

// ---- État -------------------------------------------------------------------

async function ongletEtat(zone) {
  let s = etat.serveur;
  try {
    s = etat.serveur = await appeler("GET", "/api/etat");
  } catch {
    s = null;
  }
  const ligne = (texte, classe, detail) => {
    const l = element("div", "etat");
    l.append(element("span", `point ${classe}`), element("span", null, texte));
    if (detail) l.append(element("span", "detail", detail));
    return l;
  };
  const google = { true: ["connecté", "pret"], false: ["non connecté", "deconnecte"], null: ["à vérifier", ""] }[String(s?.google ?? null)];
  const etats = element("div", "etats");
  etats.append(
    ligne(`Agent First · ${s ? "prêt" : "arrêté"}`, s ? "pret" : "panne"),
    ligne(`Chrome dédié · ${!s ? "inconnu" : s.chrome ? "ouvert" : "s'ouvrira au premier message"}`, s?.chrome ? "pret" : ""),
    ligne(`Compte Google · ${google[0]}`, google[1]),
  );
  const fournisseurs = element("div", "etats");
  fournisseurs.append(...etat.fournisseurs.map((f) => ligne(f.nom, f.etat, libelleEtat(f.etat, f.detail) || (f.etat === "pret" ? "prêt" : "pas encore utilisé"))));
  zone.replaceChildren(section("Agent First", etats), section("Fournisseurs actifs", fournisseurs));
}
