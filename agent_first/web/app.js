// agent.first — état, affichage et événements de l'app.
import { appeler, appelerEnDirect } from "./api.js";
import {
  OUTILS, avertissementMedia, cheminCourt, choixDisponible, estInterrompue, formaterDate, formaterDuree, fournisseurDuMessage,
  groupesParDate, libelleDe, limiteOption, metaMessage, outilDuMessage, outilPossible, tailleFichier, texteAttente, texteRelais,
  titreDepuis, trierPieces,
} from "./outils.js";
import { avancementPlan, detailTour, infoResultat, libelleEtape, lignesBilan, nombreLignes, normaliserAction, resumeDiff } from "./outils_cowork.js";

const $ = (id) => document.getElementById(id);
const CLE_DEFAUT = "agent.first.defaut";
const CLE_BARRE = "agent.first.barre-repliee";
const CLE_DOSSIER = "agent.first.dossier";
const FIN_DE_TACHE = ["termine", "limite", "arret", "erreur", "question"];
const VERT = "var(--vert)";
const ORANGE = "var(--ambre)";
const ROUGE = "var(--rouge)";
const GRIS = "var(--texte-3)";
// Exemples proposés dans une conversation vide : [texte, outil].
const SUGGESTIONS = [
  ["Explique-moi simplement comment fonctionne un moteur électrique", null],
  ["Un renard roux dans une forêt enneigée, lumière douce du matin", "image"],
  ["Une vague qui se brise au ralenti au coucher du soleil", "video"],
  ["Un morceau lo-fi calme pour travailler, avec du piano et une pluie légère", "musique"],
];
const ETATS_GOOGLE = {
  true: ["connecté", VERT],
  false: ["non connecté", ROUGE],
  null: ["à vérifier", GRIS],
};

const etat = {
  fournisseurs: [], // les assistants proposés (/api/fournisseurs) : nom, libellé, outils, modèles, niveaux
  fournisseur: "gemini", // l'assistant de la conversation affichée (ou de la prochaine)
  reglagesApp: { redondance: false, ordre: [] }, // gardés par Agent First (Paramètres)
  modes: { modeles: [], niveaux: [] }, // ceux de l'assistant choisi
  modele: null,
  niveau: null,
  outil: null, // « image », « video », « musique » : Gemini crée ce média (Chat seulement)
  pieces: [], // fichiers (File) joints au prochain message du Chat
  envoi: null, // conversation dont un message du Chat attend sa réponse (pour l'arrêter)
  filtreMedias: "", // galerie du tableau de bord : "", "image", "video", "audio"
  courante: null, // identifiant de la conversation affichée ; null = nouvelle conversation
  occupe: false,
  periode: "7j",
  serveur: null, // dernière réponse de /api/etat (null = Agent First injoignable)
  mode: "chat", // « chat » ou « cowork »
  dossier: null, // dossier de travail (mode Cowork)
  tache: null, // conversation dont une tâche Cowork est suivie en direct
  flux: null, // EventSource de cette tâche
  actives: new Set(), // conversations dont une tâche tourne (app ou API réseau)
  attentes: new Set(), // conversations dont une tâche attend un accord
};

// ---------- outils ----------

function element(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

function icone(nom) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${nom}`);
  svg.append(use);
  return svg;
}

function lire(cle, defaut) {
  try {
    return JSON.parse(localStorage.getItem(cle)) ?? defaut;
  } catch {
    return defaut;
  }
}

function ecrire(cle, valeur) {
  try {
    localStorage.setItem(cle, JSON.stringify(valeur));
  } catch {
    // stockage indisponible : la préférence ne sera simplement pas gardée
  }
}

function signaler(texte, couleur) {
  $("pastille-texte").textContent = texte;
  $("pastille-point").style.background = couleur;
}

function afficherVue(nom) {
  $("vue-accueil").hidden = nom !== "accueil";
  $("vue-discussion").hidden = nom !== "discussion";
  $("aller-accueil").classList.toggle("actif", nom === "accueil");
}

function defilerEnBas() {
  const fil = $("fil");
  fil.scrollTop = fil.scrollHeight;
}

function ajusterSaisie() {
  const saisie = $("saisie");
  saisie.style.height = "auto";
  saisie.style.height = `${Math.min(saisie.scrollHeight, 220)}px`;
}

// ---------- état d'Agent First et de Gemini ----------

async function verifierEtat() {
  try {
    etat.serveur = await appeler("GET", "/api/etat");
    const [texte, couleur] = ETATS_GOOGLE[String(etat.serveur.google)];
    $("etat-google").textContent = `Gemini · ${texte}`;
    $("point-google").style.background = couleur;
    if (!etat.occupe) signaler(`${libelle()} prêt`, VERT);
  } catch {
    etat.serveur = null;
    $("etat-google").textContent = "Agent First arrêté";
    $("point-google").style.background = ROUGE;
    if (!etat.occupe) signaler("Agent First arrêté", ROUGE);
  }
}

// ---------- modèle et niveau ----------

async function chargerModes() {
  try {
    [etat.fournisseurs, etat.reglagesApp] = await Promise.all([appeler("GET", "/api/fournisseurs"), appeler("GET", "/api/reglages")]);
  } catch (e) {
    signaler(e.message, ROUGE);
  }
  appliquerFournisseur(etat.fournisseur, etat.modele, etat.niveau);
}

// L'assistant par défaut (Paramètres), s'il est encore proposé ; Gemini sinon.
function fournisseurParDefaut(defaut) {
  return etat.fournisseurs.some((f) => f.nom === defaut.fournisseur) ? defaut.fournisseur : "gemini";
}

function libelle(nom = etat.fournisseur) {
  return libelleDe(etat.fournisseurs, nom);
}

function fournisseurCourant() {
  return etat.fournisseurs.find((f) => f.nom === etat.fournisseur)
    ?? { nom: etat.fournisseur, libelle: libelle(), outils: etat.fournisseur === "gemini" ? Object.keys(OUTILS) : [], modeles: [], niveaux: [] };
}

// L'assistant du compositeur : ses modèles, ses niveaux, ce qu'il sait créer.
function appliquerFournisseur(nom, modele, niveau) {
  etat.fournisseur = nom ?? "gemini";
  const f = fournisseurCourant();
  etat.modes = { modeles: f.modeles ?? [], niveaux: f.niveaux ?? [] };
  if (!outilPossible(f, etat.outil)) etat.outil = null;
  choisirReglages(modele, niveau);
  dessinerOutil();
}

// Choisir un assistant (et son modèle) dans le menu ou sur l'accueil d'une conversation. Une
// conversation commencée continue chez lui : il reçoit l'historique avec le prochain message.
async function choisirAssistant(nom, modele) {
  if (nom === etat.fournisseur) {
    etat.modele = modele;
    dessinerReglages();
    return;
  }
  if (etat.occupe) {
    signaler("Attends la fin de la réponse en cours", ORANGE);
    return;
  }
  if (etat.courante && etat.mode === "cowork") {
    signaler("Pour Cowork, choisis l'assistant dans une nouvelle conversation", ORANGE);
    return;
  }
  if (etat.courante) {
    try {
      await appeler("POST", `/api/conversations/${etat.courante}/fournisseur`, { fournisseur: nom, modele });
    } catch (e) {
      signaler(e.message, ROUGE);
      return;
    }
    $("fil").append(element("div", "bulle note", `La suite part chez ${libelle(nom)} : il reçoit l'historique de la conversation.`));
    defilerEnBas();
  }
  appliquerFournisseur(nom, modele, null);
  $("fil").querySelector(".vide-discussion")?.replaceWith(accueilDiscussion());
  signaler(`${libelle(nom)} choisi`, VERT);
}

// État de connexion d'un assistant, lu par /api/etat (null : pas encore vérifié).
function etatConnexion(nom) {
  const s = etat.serveur;
  if (!s) return ["inconnu", GRIS];
  const connecte = nom === "gemini" ? s.google : s.fournisseurs?.[nom];
  if (connecte === true) return ["connecté", VERT];
  if (connecte === false) return ["non connecté", ROUGE];
  const f = etat.fournisseurs.find((x) => x.nom === nom);
  return [!s.chrome || (f && !f.ouvert && nom !== "gemini") ? "s'ouvrira à son premier message" : "à vérifier", GRIS];
}

function choisirReglages(modele, niveau) {
  const { modeles, niveaux } = etat.modes;
  // un choix bloqué par la limite du compte est remplacé par un choix disponible
  etat.modele = choixDisponible(modeles, modele);
  etat.niveau = choixDisponible(niveaux, niveau);
  dessinerReglages();
}

function optionsMenu(liste, choisi, choisir, site = "Gemini") {
  return liste.map((o) => {
    const option = element("button", "option");
    option.type = "button";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(o.nom === choisi));
    option.append(element("span", "option-nom", o.nom ?? "Modèle par défaut"), element("span", "option-desc", o.description));
    const limite = limiteOption(o);
    if (limite) {
      option.classList.add("bloquee"); // le site refusera ce choix jusqu'à la réinitialisation
      option.title = `Bloqué par la limite de ton compte ${site} jusqu'au ${limite}`;
    }
    option.addEventListener("click", () => {
      choisir(o.nom);
      fermerMenus();
      dessinerReglages();
    });
    return option;
  });
}

function dessinerReglages() {
  const plusieurs = etat.fournisseurs.length > 1;
  $("nom-modele").textContent = plusieurs ? [libelle(), etat.modele].filter(Boolean).join(" · ") : etat.modele ?? "Modèle";
  $("bouton-modele").title = plusieurs ? "Assistant et modèle" : "Modèle";
  $("menu-modeles").replaceChildren(
    ...(plusieurs ? menuAssistants() : optionsMenu(etat.modes.modeles, etat.modele, (nom) => (etat.modele = nom), libelle())),
  );
  $("menu-niveaux").replaceChildren(...optionsMenu(etat.modes.niveaux, etat.niveau, (nom) => (etat.niveau = nom), libelle()));
  $("bouton-niveau").parentElement.hidden = !etat.modes.niveaux.length;
}

// Le menu des modèles, rangés par assistant (avec son état de connexion).
function menuAssistants() {
  const contenu = [];
  for (const f of etat.fournisseurs) {
    const titre = element("div", "menu-groupe");
    const point = element("span", "point");
    const [texte, couleur] = etatConnexion(f.nom);
    point.style.background = couleur;
    point.title = texte;
    titre.append(point, element("span", "menu-groupe-nom", f.libelle));
    const cree = f.outils.map((o) => OUTILS[o]?.nom.toLowerCase()).filter(Boolean);
    titre.append(element("span", "menu-groupe-info", cree.length ? `texte, ${cree.join(", ")}` : "texte"));
    contenu.push(titre);
    const modeles = f.modeles.length ? f.modeles : [{ nom: null, description: "Celui déjà choisi sur le site", actif: true }];
    const choisi = f.nom === etat.fournisseur ? etat.modele : undefined;
    contenu.push(...optionsMenu(modeles, choisi, (nom) => choisirAssistant(f.nom, nom), f.libelle));
  }
  // La redondance, à portée de main (aussi dans Paramètres, avec l'ordre des assistants).
  const redondance = element("button", "option option-redondance");
  redondance.type = "button";
  redondance.setAttribute("role", "menuitemcheckbox");
  redondance.setAttribute("aria-checked", String(etat.reglagesApp.redondance));
  redondance.append(
    element("span", "option-nom", `Redondance : ${etat.reglagesApp.redondance ? "activée" : "désactivée"}`),
    element("span", "option-desc", etat.reglagesApp.redondance
      ? "Un assistant saturé passe la main au suivant"
      : "Un assistant saturé : on te propose les autres"),
  );
  redondance.addEventListener("click", async () => {
    await enregistrerReglages({ redondance: !etat.reglagesApp.redondance });
    dessinerReglages();
  });
  contenu.push(redondance);
  return contenu;
}

// Menu « Créer » : une réponse écrite, ou une image, une vidéo, de la musique.
function dessinerOutil() {
  const choisi = OUTILS[etat.outil] ?? null;
  const qui = libelle();
  const f = fournisseurCourant();
  $("nom-outil").textContent = choisi?.nom ?? "Texte";
  $("icone-outil").firstElementChild.setAttribute("href", `#${choisi?.icone ?? "i-texte"}`);
  $("bouton-outil").classList.toggle("actif", Boolean(choisi));
  const descriptions = { null: "Réponse écrite", image: `${qui} crée une image`, video: "Veo : souvent plusieurs minutes", musique: "Un morceau audio" };
  const options = [[null, { nom: "Texte", icone: "i-texte" }], ...Object.entries(OUTILS)].map(([cle, o]) => {
    const option = element("button", "option option-outil");
    option.type = "button";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(cle === etat.outil));
    const possible = outilPossible(f, cle);
    const textes = element("span", "option-textes");
    textes.append(element("span", "option-nom", o.nom), element("span", "option-desc", possible ? descriptions[cle] : `Pas avec ${qui} : choisis Gemini`));
    option.append(icone(o.icone), textes);
    if (!possible) {
      option.disabled = true; // ChatGPT ne fait pas de vidéo, Claude ne crée pas de média…
      return option;
    }
    option.addEventListener("click", () => {
      etat.outil = cle;
      fermerMenus();
      dessinerOutil();
      $("saisie").focus();
    });
    return option;
  });
  $("menu-outils").replaceChildren(...options);
  $("zone-outil").hidden = etat.mode === "cowork";
  $("saisie").placeholder = etat.mode === "cowork" ? "Décris une tâche à Cowork…" : choisi?.saisie ?? `Demande à ${qui}…`;
  $("pied").textContent = choisi
    ? `${choisi.nom} : ${qui} crée le média, gardé dans l'historique et téléchargeable · Entrée pour envoyer`
    : "Entrée pour envoyer · Maj+Entrée pour aller à la ligne";
}

// bouton → menu qu'il ouvre, au-dessus de la zone de saisie
const MENUS = { "bouton-outil": "menu-outils", "bouton-modele": "menu-modeles", "bouton-niveau": "menu-niveaux" };

function basculerMenu(bouton) {
  const ouvrir = $(MENUS[bouton]).hidden;
  fermerMenus();
  $(MENUS[bouton]).hidden = !ouvrir;
  $(bouton).setAttribute("aria-expanded", String(ouvrir));
}

function fermerMenus() {
  for (const [bouton, menu] of Object.entries(MENUS)) {
    $(menu).hidden = true;
    $(bouton).setAttribute("aria-expanded", "false");
  }
}

// ---------- barre latérale ----------

async function chargerConversations() {
  const recherche = $("recherche").value.trim();
  const liste = $("liste-conversations");
  let conversations;
  try {
    conversations = await appeler("GET", `/api/conversations?${new URLSearchParams({ recherche })}`);
  } catch {
    liste.replaceChildren(element("p", "vide", "Historique indisponible."));
    return;
  }
  if (!conversations.length) {
    liste.replaceChildren(element("p", "vide", recherche ? "Aucun résultat." : "Tes conversations apparaîtront ici."));
    return;
  }
  const contenu = [];
  for (const groupe of groupesParDate(conversations)) {
    contenu.push(element("div", "groupe-titre", groupe.titre));
    for (const c of groupe.conversations) {
      const bouton = element("button", "conversation");
      bouton.type = "button";
      bouton.title = [c.fournisseur && c.fournisseur !== "gemini" ? libelle(c.fournisseur) : null, c.mode === "cowork" ? "Cowork" : null,
        c.source === "api" ? "API" : null, c.titre].filter(Boolean).join(" · ");
      bouton.classList.toggle("actif", c.id === etat.courante);
      // marque : point ambre si une tâche attend un accord, point qui pulse si elle tourne,
      // sinon terminal pour Cowork, rien pour Chat
      const marque = element("span", "marque");
      if (etat.attentes.has(c.id)) marque.classList.add("attente");
      else if (c.id === etat.tache || etat.actives.has(c.id)) marque.classList.add("en-cours");
      else if (c.mode === "cowork") marque.append(icone("i-terminal"));
      bouton.append(marque, element("span", "conversation-titre", c.titre || "Sans titre"));
      bouton.addEventListener("click", () => ouvrirConversation(c.id));
      contenu.push(bouton);
    }
  }
  liste.replaceChildren(...contenu);
}

function basculerBarre() {
  ecrire(CLE_BARRE, document.body.classList.toggle("barre-repliee"));
}

// ---------- discussion ----------

// `autres` (erreur) : les assistants à proposer à la place, [{ libelle, essayer }].
function bulle(message, reessayer = null, autres = []) {
  if (message.role === "toi") {
    const b = element("div", "bulle toi");
    const outil = OUTILS[outilDuMessage(message)];
    const texte = element("div", "texte-toi");
    if (outil) {
      const etiquette = element("span", "etiquette-outil");
      etiquette.append(icone(outil.icone), document.createTextNode(outil.nom));
      texte.append(etiquette);
    }
    texte.append(document.createTextNode(message.texte));
    if (message.medias?.length) texte.append(blocPieces(message.medias));
    b.append(texte);
    return b;
  }
  if (message.role === "relais") {
    const { texte, raison } = texteRelais(message);
    const note = element("div", "bulle note relais", texte);
    note.title = raison;
    return note;
  }
  if (message.role === "erreur") {
    const b = element("div", "bulle erreur");
    b.append(element("span", null, `Erreur : ${message.texte}`));
    const boutons = element("div", "erreur-actions");
    const tentatives = [...(reessayer ? [{ libelle: null, essayer: reessayer }] : []), ...autres];
    for (const t of tentatives) {
      const bouton = element("button", "bouton-reessayer");
      bouton.type = "button";
      bouton.append(icone("i-reessayer"), document.createTextNode(t.libelle ? `Avec ${t.libelle}` : "Réessayer"));
      if (t.libelle) bouton.title = `Envoyer ce message à ${t.libelle} (il reçoit l'historique de la conversation)`;
      bouton.addEventListener("click", () => {
        if (etat.occupe) return;
        boutons.remove(); // une seule nouvelle tentative par erreur
        t.essayer();
      });
      boutons.append(bouton);
    }
    if (tentatives.length) b.append(boutons);
    return b;
  }
  // Réponse de Gemini : du texte, sans carte ; ses médias ; le modèle et la durée en dessous, en petit.
  const carte = element("article", "bulle gemini");
  const contenu = element("div", "markdown");
  if (message.html) {
    contenu.innerHTML = message.html; // déjà nettoyé par Agent First (nh3)
    contenu.querySelectorAll("pre").forEach(ajouterCopieCode);
  } else {
    contenu.textContent = message.texte;
  }
  const copier = element("button", "icone");
  copier.type = "button";
  copier.title = "Copier la réponse";
  copier.setAttribute("aria-label", "Copier la réponse");
  copier.append(icone("i-copier"));
  copier.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(message.texte);
      signaler("Réponse copiée", VERT);
    } catch {
      signaler("Copie impossible", ROUGE);
    }
  });
  const pied = element("div", "message-pied");
  pied.append(element("span", null, metaMessage(message, libelle(fournisseurDuMessage(message)))));
  if (estInterrompue(message)) pied.append(element("span", "marque-arret", "arrêtée"));
  pied.append(copier);
  if (message.texte || message.html || !message.medias?.length) carte.append(contenu);
  if (message.medias?.length) carte.append(blocMedias(message.medias));
  carte.append(pied);
  return carte;
}

const NOMS_MEDIAS = { image: "Image", video: "Vidéo", audio: "Audio" };

// Images (cliquer pour agrandir), vidéos et sons créés par Gemini, chacun téléchargeable.
function blocMedias(medias) {
  const bloc = element("div", "medias");
  const images = element("div", "medias-images");
  for (const m of medias) {
    const url = `/api/medias/${m.id}`;
    const carte = element("figure", `media media-${m.type}`);
    if (m.type === "image") {
      const agrandir = element("button", "media-agrandir");
      agrandir.type = "button";
      agrandir.title = "Agrandir";
      const image = element("img");
      image.src = url;
      image.alt = m.description || "Image créée";
      image.loading = "lazy";
      agrandir.append(image);
      agrandir.addEventListener("click", () => ouvrirVisionneuse(m));
      carte.append(agrandir);
    } else {
      const lecteur = element(m.type === "video" ? "video" : "audio");
      lecteur.controls = true;
      lecteur.preload = "metadata";
      lecteur.src = url;
      carte.append(lecteur);
    }
    const legende = element("figcaption", "media-legende");
    const telecharger = element("a", "bouton-lien");
    telecharger.href = `${url}?telecharger=true`;
    telecharger.download = "";
    telecharger.append(icone("i-telecharger"), document.createTextNode("Télécharger"));
    const format = (m.mime.split("/")[1] ?? "").replace(/^x-/, "").toUpperCase();
    legende.append(element("span", null, [NOMS_MEDIAS[m.type] ?? "Média", format, tailleFichier(m.octets)].filter(Boolean).join(" · ")), telecharger);
    carte.append(legende);
    (m.type === "image" ? images : bloc).append(carte);
  }
  if (images.childElementCount) bloc.prepend(images);
  return bloc;
}

// Fichiers joints à un message : miniatures pour les images, puces pour le reste.
function blocPieces(medias) {
  const bloc = element("div", "pieces-message");
  for (const m of medias) {
    const url = m.url ?? `/api/medias/${m.id}`;
    if (m.type === "image") {
      const bouton = element("button", "piece-miniature");
      bouton.type = "button";
      bouton.title = m.description || "Image jointe";
      const image = element("img");
      image.src = url;
      image.alt = m.description || "Image jointe";
      bouton.append(image);
      bouton.addEventListener("click", () => ouvrirVisionneuse(m));
      bloc.append(bouton);
    } else {
      const puce = element("a", "piece-puce");
      puce.href = m.id ? `${url}?telecharger=true` : url;
      puce.download = m.description || "";
      puce.append(icone({ video: "i-video", audio: "i-musique" }[m.type] ?? "i-fichier"),
        element("span", null, m.description || "fichier"), element("span", "piece-taille", tailleFichier(m.octets)));
      bloc.append(puce);
    }
  }
  return bloc;
}

function ouvrirVisionneuse(m) {
  const url = m.url ?? `/api/medias/${m.id}`;
  $("visionneuse-image").src = url;
  $("visionneuse-image").alt = m.description || "Image";
  $("visionneuse-legende").textContent = m.description || "";
  $("visionneuse-ouvrir").href = url;
  $("visionneuse-telecharger").href = m.id ? `${url}?telecharger=true` : url;
  $("visionneuse-telecharger").hidden = !m.id;
  $("visionneuse").showModal();
}

function ajouterCopieCode(pre) {
  const bouton = element("button", "copier-code");
  bouton.type = "button";
  bouton.title = "Copier le code";
  bouton.setAttribute("aria-label", "Copier le code");
  bouton.append(icone("i-copier"));
  bouton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText((pre.querySelector("code") ?? pre).innerText);
      signaler("Code copié", VERT);
    } catch {
      signaler("Copie impossible", ROUGE);
    }
  });
  pre.append(bouton);
}

// Choisir l'assistant d'une nouvelle conversation, d'un clic.
function choixAssistants() {
  const zone = element("div", "segments choix-assistant");
  zone.setAttribute("role", "radiogroup");
  zone.setAttribute("aria-label", "Assistant");
  for (const f of etat.fournisseurs) {
    const bouton = element("button", f.nom === etat.fournisseur ? "actif" : null);
    bouton.type = "button";
    bouton.setAttribute("role", "radio");
    bouton.setAttribute("aria-checked", String(f.nom === etat.fournisseur));
    const point = element("span", "point");
    const [texte, couleur] = etatConnexion(f.nom);
    point.style.background = couleur;
    bouton.title = `${f.libelle} · ${texte}`;
    bouton.append(point, document.createTextNode(f.libelle));
    bouton.addEventListener("click", () => choisirAssistant(f.nom, null));
    zone.append(bouton);
  }
  return zone;
}

function accueilDiscussion() {
  const bloc = element("div", "vide-discussion");
  const qui = libelle();
  if (etat.fournisseurs.length > 1) bloc.append(choixAssistants());
  if (etat.mode === "cowork") {
    bloc.append(element("h1", null, `Travaille avec ${qui} sur ton PC`));
    const aide = element("p");
    if (etat.dossier) {
      aide.append(
        document.createTextNode(`${qui} fait un plan, lit, crée et modifie des fichiers, lance des commandes et des serveurs dans `),
        element("code", null, cheminCourt(etat.dossier)),
        document.createTextNode(", puis vérifie son travail. Les actions risquées attendent ton accord."),
      );
      bloc.append(aide);
    } else {
      aide.textContent = "Choisis d'abord le dossier de travail, puis décris la tâche.";
      const choisir = element("button", "bouton-secondaire", "Choisir un dossier");
      choisir.type = "button";
      choisir.addEventListener("click", choisirDossier);
      bloc.append(aide, choisir);
    }
    return bloc;
  }
  const f = fournisseurCourant();
  const cree = f.outils.map((o) => OUTILS[o]?.article.replace(/^d'|^de /, "")).filter(Boolean);
  bloc.append(
    element("h1", null, `Discute avec ${qui}`),
    element("p", null, cree.length
      ? `Pose ta question, ou choisis « Créer » sous la zone de saisie pour : ${cree.join(", ")}.`
      : `Pose ta question. Pour créer une image, une vidéo ou de la musique, choisis Gemini.`),
  );
  const suggestions = element("div", "suggestions");
  for (const [texte, outil] of SUGGESTIONS.filter(([, o]) => outilPossible(f, o))) {
    const bouton = element("button", "suggestion");
    bouton.type = "button";
    bouton.append(icone(OUTILS[outil]?.icone ?? "i-messages"), element("span", null, texte));
    bouton.addEventListener("click", () => {
      etat.outil = outil;
      dessinerOutil();
      $("saisie").value = texte;
      ajusterSaisie();
      $("saisie").focus();
    });
    suggestions.append(bouton);
  }
  bloc.append(suggestions);
  return bloc;
}

function nouvelleConversation() {
  etat.courante = null;
  etat.outil = null;
  viderPieces();
  if (etat.mode === "cowork") etat.dossier = lire(CLE_DOSSIER, null);
  $("titre-conversation").textContent = "Nouvelle conversation";
  const defaut = lire(CLE_DEFAUT, {});
  appliquerFournisseur(fournisseurParDefaut(defaut), defaut.modele, defaut.niveau);
  dessinerMode();
  dessinerProcessus([]);
  $("fil").replaceChildren(accueilDiscussion());
  afficherVue("discussion");
  chargerConversations();
  $("saisie").focus();
}

async function ouvrirConversation(identifiant) {
  try {
    const { conversation, messages, tache } = await appeler("GET", `/api/conversations/${identifiant}`);
    etat.courante = conversation.id;
    viderPieces();
    etat.mode = conversation.mode ?? "chat";
    etat.dossier = conversation.dossier ?? null;
    $("titre-conversation").textContent = conversation.titre || "Conversation";
    appliquerFournisseur(conversation.fournisseur ?? "gemini", conversation.modele, conversation.niveau);
    // on reprend là où on en était : le dernier outil demandé (une autre image…)
    const demandes = messages.filter((m) => m.role === "toi");
    etat.outil = etat.mode === "chat" && demandes.length ? outilDuMessage(demandes[demandes.length - 1]) : null;
    if (!outilPossible(fournisseurCourant(), etat.outil)) etat.outil = null;
    dessinerMode();
    const fil = $("fil");
    fil.replaceChildren();
    const ajouter = creerRenduCowork(fil, false);
    // Tâche en cours : ses étapes viendront du flux (rejouées, accord compris) ; ici, seulement ce qui précède.
    const fin = tache?.en_cours ? messages.map((m) => m.role).lastIndexOf("toi") + 1 : messages.length;
    for (const m of messages.slice(0, fin)) {
      if (m.role === "cowork") ajouter(JSON.parse(m.details));
      else fil.append(bulle(m));
    }
    afficherVue("discussion");
    defilerEnBas();
    dessinerProcessus([]);
    if (etat.mode === "cowork") chargerProcessus(conversation.id);
    if (tache?.en_cours) ecouterFlux(conversation.id, 0);
    else chargerConversations();
    dessinerBandeau();
    $("saisie").focus();
  } catch (e) {
    signaler(e.message, ROUGE);
  }
}

async function envoyer(texteImpose = null, outilImpose = undefined, piecesImposees = null) {
  const texte = (texteImpose ?? $("saisie").value).trim();
  if (!texte || etat.occupe) return;
  if (etat.mode === "cowork") return envoyerCowork(texte);
  const outil = outilImpose === undefined ? etat.outil : outilImpose;
  const pieces = piecesImposees ?? etat.pieces.slice();
  etat.occupe = true;
  $("form-saisie").classList.add("occupe");
  $("saisie").value = "";
  ajusterSaisie();
  viderPieces();

  const fil = $("fil");
  fil.querySelector(".vide-discussion")?.remove();
  const apercus = pieces.map((f) => ({ type: f.type.split("/")[0], description: f.name, octets: f.size, url: URL.createObjectURL(f) }));
  fil.append(bulle({ role: "toi", texte, details: outil ? JSON.stringify({ outil }) : null, medias: apercus }));
  const attente = element("div", "bulle attente");
  let qui = libelle(); // l'assistant qui répond (la redondance peut en changer en route)
  const libelleAttente = element("span", null, pieces.length ? "Envoi des fichiers…" : texteAttente(outil, qui));
  attente.append(element("span", "points"), libelleAttente);
  fil.append(attente);
  defilerEnBas();
  if (!etat.courante) $("titre-conversation").textContent = titreDepuis(texte);

  // La réponse s'écrit dans cette bulle pendant que l'assistant l'écrit.
  const direct = element("article", "bulle gemini");
  const texteDirect = element("div", "markdown en-direct");
  const piedDirect = element("div", "message-pied", `${qui} écrit…`);
  direct.append(texteDirect, piedDirect);
  let enCours = attente;

  const debut = Date.now();
  signaler(texteAttente(outil, qui), ORANGE);
  const minuteur = setInterval(() => {
    const ecoule = `${texteAttente(outil, qui)} ${formaterDuree((Date.now() - debut) / 1000)}`;
    libelleAttente.textContent = ecoule;
    signaler(ecoule, ORANGE);
  }, 1000);

  try {
    const corps = { texte, modele: etat.modele, niveau: etat.niveau, ...(outil ? { outil } : {}) };
    if (pieces.length) corps.pieces = await Promise.all(pieces.map(async (f) => ({ nom: f.name, mime: f.type || "application/octet-stream", donnees: await lireBase64(f) })));
    if (!etat.courante) {
      const conversation = await appeler("POST", "/api/conversations", { modele: etat.modele, niveau: etat.niveau, fournisseur: etat.fournisseur });
      etat.courante = conversation.id;
    }
    etat.envoi = etat.courante;
    montrerArret(true);
    const fin = await appelerEnDirect(`/api/conversations/${etat.courante}/messages?direct=true`, corps, (ev) => {
      const enBas = fil.scrollHeight - fil.scrollTop - fil.clientHeight < 80;
      if (ev.type === "relais") {
        // L'assistant est saturé : un autre reprend depuis le début (son début de réponse est abandonné).
        const note = element("div", "bulle note relais", `${ev.de} est indisponible : ${ev.vers} prend le relais.`);
        note.title = ev.raison ?? "";
        enCours.before(note);
        qui = ev.vers;
        texteDirect.textContent = "";
        piedDirect.textContent = `${qui} écrit…`;
        libelleAttente.textContent = texteAttente(outil, qui);
        if (enCours !== attente) {
          enCours.replaceWith(attente);
          enCours = attente;
        }
        appliquerFournisseur(ev.fournisseur, null, null);
        signaler(`${ev.vers} prend le relais`, ORANGE);
      } else if (ev.type === "texte") {
        texteDirect.textContent = ev.texte;
        if (enCours !== direct) {
          enCours.replaceWith(direct);
          enCours = direct;
        }
      } else {
        return;
      }
      if (enBas) defilerEnBas();
    });
    if (fin?.type === "erreur") throw Object.assign(new Error(fin.erreur), { autres: fin.autres ?? [] });
    if (fin?.type === "arrete") {
      enCours.replaceWith(element("div", "bulle note", `Message arrêté avant son envoi à ${qui}.`));
      $("saisie").value = texte;
      ajusterSaisie();
      signaler("Message arrêté", GRIS);
      return;
    }
    if (fin?.type !== "fin") throw new Error("Réponse interrompue (Agent First arrêté ?).");
    const { message, medias_perdus: perdus } = fin;
    enCours.replaceWith(bulle(message));
    const avertissement = estInterrompue(message) ? null : avertissementMedia(outil, message.medias, perdus, qui);
    if (avertissement) fil.append(element("div", "bulle note", avertissement));
    const n = message.medias?.length ?? 0;
    signaler(estInterrompue(message) ? "Réponse arrêtée" : n ? `${n} média${n > 1 ? "s" : ""} reçu${n > 1 ? "s" : ""}` : `${qui} prêt`, VERT);
    verifierEtat(); // Chrome et le compte viennent de servir : l'état affiché se met à jour
  } catch (e) {
    // Sans la redondance, Agent First propose les autres assistants : l'utilisateur choisit.
    const autres = (e.autres ?? []).slice(0, 3).map((nom) => ({
      libelle: libelle(nom),
      essayer: async () => {
        await choisirAssistant(nom, null);
        if (etat.fournisseur === nom) envoyer(texte, outil, pieces);
      },
    }));
    enCours.replaceWith(bulle({ role: "erreur", texte: e.message }, () => envoyer(texte, outil, pieces), autres));
    $("saisie").value = texte; // pour pouvoir le renvoyer
    ajusterSaisie();
    if (!etat.pieces.length) ajouterPieces(pieces); // les fichiers aussi
    signaler(e.message === "Agent First n'est pas démarré." ? "Agent First arrêté" : "Erreur", ROUGE);
    verifierEtat(); // met à jour l'état du compte (la pastille garde l'erreur tant que l'envoi est en cours)
    if (/n'est pas proposé|est bloqué/.test(e.message)) chargerModes(); // menus à jour (choix bloqués)
  } finally {
    clearInterval(minuteur);
    etat.occupe = false;
    etat.envoi = null;
    montrerArret(false);
    $("exporter").hidden = !etat.courante;
    $("form-saisie").classList.remove("occupe");
    defilerEnBas();
    chargerConversations();
  }
}

function lireBase64(fichier) {
  return new Promise((ok, ko) => {
    const lecteur = new FileReader();
    lecteur.onload = () => ok(String(lecteur.result).split(",", 2)[1] ?? "");
    lecteur.onerror = () => ko(new Error(`Fichier illisible : ${fichier.name}`));
    lecteur.readAsDataURL(fichier);
  });
}

// ---------- fichiers joints ----------

function ajouterPieces(fichiers) {
  if (etat.mode === "cowork") {
    signaler(`En Cowork, ${libelle()} lit les fichiers du dossier de travail`, GRIS);
    return;
  }
  const { acceptees, refus } = trierPieces(etat.pieces.length, [...fichiers]);
  etat.pieces.push(...acceptees);
  dessinerPieces();
  if (refus.length) signaler(`Non joint : ${refus.join(" ; ")}`, ROUGE);
  else if (acceptees.length) signaler(`${etat.pieces.length} fichier${etat.pieces.length > 1 ? "s" : ""} joint${etat.pieces.length > 1 ? "s" : ""}`, VERT);
}

function viderPieces() {
  etat.pieces = [];
  dessinerPieces();
}

function dessinerPieces() {
  const zone = $("pieces");
  zone.querySelectorAll("img").forEach((i) => URL.revokeObjectURL(i.src));
  zone.replaceChildren(
    ...etat.pieces.map((f, rang) => {
      const puce = element("span", "piece-jointe");
      puce.title = `${f.name} · ${tailleFichier(f.size)}`;
      if (f.type.startsWith("image/")) {
        const image = element("img");
        image.src = URL.createObjectURL(f);
        image.alt = "";
        puce.append(image);
      } else {
        puce.append(icone(f.type.startsWith("video/") ? "i-video" : f.type.startsWith("audio/") ? "i-musique" : "i-fichier"));
      }
      const retirer = element("button", "piece-retirer");
      retirer.type = "button";
      retirer.title = `Retirer ${f.name}`;
      retirer.setAttribute("aria-label", retirer.title);
      retirer.append(icone("i-fermer"));
      retirer.addEventListener("click", () => {
        etat.pieces.splice(rang, 1);
        dessinerPieces();
      });
      puce.append(element("span", "piece-nom", f.name), retirer);
      return puce;
    }),
  );
  zone.hidden = !etat.pieces.length;
}

function montrerArret(visible) {
  $("arreter").hidden = !visible;
  $("arreter").title = etat.tache ? "Arrêter la tâche après l'étape en cours" : `Arrêter la réponse de ${libelle()} (ce qu'il a écrit est gardé)`;
}

// ---------- Cowork ----------

// Une étape = une ligne monospace : point d'état, verbe (Write, Edit, Run…), détail, info, et un
// contenu qu'on peut déplier (diff, sortie de commande, fichier écrit).
function ligneEtape(ev, interactif) {
  const { verbe, detail } = libelleEtape(ev);
  const { action, champs } = normaliserAction(ev);
  const etape = element("details", "etape");
  etape.dataset.action = action;
  etape.dataset.detail = detail;
  const resume = element("summary");
  resume.title = detail;
  const chevron = icone("i-chevron");
  chevron.classList.add("chevron");
  resume.append(
    element("span", interactif ? "point-etat attente" : "point-etat"),
    element("span", "etape-verbe", verbe),
    element("span", "etape-detail", detail),
    element("span", "etape-info"),
    chevron,
  );
  etape.append(resume);
  if (action === "create") {
    resume.querySelector(".etape-info").textContent = nombreLignes(champs.content);
    if (champs.content) ajouterCorps(etape, champs.content, false);
  }
  return etape;
}

// Action non exécutée parce qu'une action précédente du même message a échoué.
function ligneSautee(ev) {
  const { verbe, detail } = libelleEtape(ev);
  const ligne = element("div", "etape sautee");
  ligne.title = "Non exécutée : une action précédente du même message a échoué";
  ligne.append(element("span", "point-etat"), element("span", "etape-verbe", verbe), element("span", "etape-detail", detail), element("span", "etape-info", "sautée"));
  return ligne;
}

function ajouterCorps(etape, texte, ouvert) {
  etape.querySelector(".etape-corps")?.remove();
  const corps = element("div", "etape-corps", texte);
  etape.append(corps);
  etape.classList.add("a-corps");
  etape.open = ouvert;
  return corps;
}

function marquerEtape(etape, etatPoint) {
  etape.querySelector(".point-etat").className = `point-etat ${etatPoint}`;
}

function afficherDiff(corps, diff) {
  for (const ligne of diff.split("\n")) {
    const classe = ligne.startsWith("@@") ? "repere" : ligne.startsWith("+") ? "plus" : ligne.startsWith("-") ? "moins" : "contexte";
    corps.append(element("div", classe, ligne));
  }
}

function ajouterResultat(etape, ev) {
  marquerEtape(etape, ev.ok ? "ok" : "ko");
  const info = etape.querySelector(".etape-info");
  const action = etape.dataset.action;
  if (ev.diff) {
    const { plus, moins } = resumeDiff(ev.diff);
    info.replaceChildren(element("span", "plus", `+${plus}`), document.createTextNode(" "), element("span", "moins", `−${moins}`));
    afficherDiff(ajouterCorps(etape, "", action === "edit"), ev.diff); // une réécriture complète reste repliée
  } else if (!ev.ok) {
    info.textContent = ev.code ? `code ${ev.code}` : infoResultat(action, ev.corps) || "échec";
    ajouterCorps(etape, ev.corps, true);
  } else if (["run", "read", "search", "list", "visit", "start", "logs", "stop"].includes(action)) {
    info.textContent = infoResultat(action, ev.corps);
    ajouterCorps(etape, ev.corps, false);
  }
}

// Évènement sans action (refus, autorisation d'office, limite, arrêt…) : une ligne de texte discrète.
function noteEtape(ev, etatPoint) {
  const { titre, detail } = libelleEtape(ev);
  const note = element("div", "etape-note");
  note.append(element("span", `point-etat ${etatPoint}`), element("span", null, titre));
  if (detail) {
    note.append(element("span", "etape-detail", detail));
    note.title = detail;
  }
  return note;
}

// Réponse hors format : repliée, avec ce que Gemini a écrit (pour comprendre ce qui s'est passé).
function noteFormat(ev) {
  const bloc = element("details", "format-casse");
  const resume = element("summary");
  resume.append(element("span", "point-etat decision"), element("span", null, libelleEtape(ev).titre));
  bloc.append(resume);
  if (ev.corps) {
    resume.append(element("span", "etape-info", "voir ce qu'il a écrit"));
    bloc.append(element("div", "etape-corps", ev.corps));
  }
  return bloc;
}

function carteDemande(ev, detail, interactif) {
  const carte = element("div", "accord");
  const titre = element("div", "accord-titre");
  titre.append(icone("i-alerte"), element("span", null, interactif ? "Autoriser cette action ?" : "Action soumise à ton accord"));
  carte.append(titre);
  if (detail) carte.append(element("code", "accord-code", detail));
  const raison = ev.raison ? ev.raison[0].toUpperCase() + ev.raison.slice(1) : "Action jugée dangereuse";
  carte.append(element("div", "accord-raison", `${raison}.`));
  if (!interactif) {
    carte.append(element("div", "accord-decision", "Décision déjà prise."));
    return carte;
  }
  const actions = element("div", "accord-actions");
  const toujours = element("label");
  const caseToujours = element("input");
  caseToujours.type = "checkbox";
  toujours.append(caseToujours, document.createTextNode("Toujours autoriser ce type d'action ici"));
  const refuser = element("button", "bouton-refuser", "Refuser");
  refuser.type = "button";
  const continuer = element("button", "bouton-continuer", "Autoriser");
  continuer.type = "button";
  const decider = async (reponse) => {
    actions.replaceWith(element("div", "accord-decision", reponse === "continuer" ? "Autorisée." : "Refusée."));
    signaler("Cowork travaille…", ORANGE);
    try {
      await appeler("POST", `/api/cowork/${etat.tache}/decision`, { etape: ev.etape, reponse, toujours: caseToujours.checked });
    } catch (e) {
      signaler(e.message, ROUGE);
    }
  };
  refuser.addEventListener("click", () => decider("refuser"));
  continuer.addEventListener("click", () => decider("continuer"));
  actions.append(toujours, refuser, continuer);
  carte.append(actions);
  return carte;
}

function remplirPlan(carte, etapes) {
  const { faites, total } = avancementPlan(etapes);
  const titre = element("div", "plan-titre");
  titre.append(element("span", null, "Plan"), element("span", "plan-avancement", `${faites}/${total}`));
  const liste = element("ul", "plan-liste");
  for (const e of etapes) {
    const ligne = element("li", e.fait ? "fait" : null);
    ligne.append(element("span", "plan-case", e.fait ? "✓" : ""), element("span", null, e.texte));
    liste.append(ligne);
  }
  carte.replaceChildren(titre, liste);
}

// La carte de plan à mettre à jour : la dernière du fil, si aucun message de l'utilisateur ne la suit.
function cartePlanCourante(conteneur) {
  const cartes = conteneur.querySelectorAll(":scope > .carte-plan");
  const derniere = cartes[cartes.length - 1];
  for (let suivant = derniere?.nextElementSibling; suivant; suivant = suivant.nextElementSibling) {
    if (suivant.matches(".bulle.toi")) return null;
  }
  return derniere ?? null;
}

function bilanVide(bilan) {
  return !bilan || (!bilan.crees?.length && !bilan.modifies?.length && !bilan.supprimes?.length
    && !bilan.commandes?.length && !bilan.verifications && !bilan.plan_inacheve?.length && !bilan.processus?.length);
}

// Ce qu'Agent First a constaté, indépendamment de ce que Gemini annonce.
function carteBilan(bilan) {
  const { compteurs, fichiers } = lignesBilan(bilan);
  const carte = element("div", "carte-bilan");
  const titre = element("div", "bilan-titre");
  titre.append(element("span", null, "Bilan d'Agent First"), element("span", "bilan-compteurs", compteurs));
  carte.append(titre);
  if (fichiers.length) {
    const liste = element("div", "bilan-fichiers");
    for (const { signe, chemin } of fichiers) {
      const classe = { "+": "plus", "~": "modif", "−": "moins" }[signe];
      const bouton = element("button", `bilan-fichier ${classe}`, `${signe} ${chemin}`);
      bouton.type = "button";
      bouton.title = "Voir l'étape correspondante";
      bouton.addEventListener("click", () => montrerEtape(chemin));
      liste.append(bouton);
    }
    carte.append(liste);
  }
  for (const c of bilan.commandes ?? []) {
    if (c.code !== null && c.code !== undefined && c.code !== 0) carte.append(element("div", "bilan-echec", `✗ ${c.texte} (code ${c.code})`));
  }
  if (bilan.plan_inacheve?.length) carte.append(element("div", "bilan-alerte", `Étapes du plan non cochées : ${bilan.plan_inacheve.join(" ; ")}`));
  for (const p of bilan.processus ?? []) carte.append(element("div", "bilan-processus", `● #${p.id} ${p.commande} tourne encore`));
  return carte;
}

function montrerEtape(chemin) {
  const etapes = [...$("fil").querySelectorAll("details.etape")].filter((e) => e.dataset.detail === chemin);
  const derniere = etapes[etapes.length - 1];
  if (!derniere) return;
  if (derniere.classList.contains("a-corps")) derniere.open = true;
  derniere.scrollIntoView({ behavior: "smooth", block: "center" });
}

function carteQuestion(ev, interactif) {
  const carte = element("div", "carte-question");
  const titre = element("div", "question-titre");
  titre.append(icone("i-messages"), element("span", null, "Gemini te demande"));
  carte.append(titre, element("div", "question-texte", ev.question));
  if (interactif) carte.append(element("div", "question-aide", "Réponds dans la zone de saisie : Gemini reprendra la tâche là où il s'est arrêté."));
  return carte;
}

// Affiche les étapes d'une tâche dans `conteneur` ; `interactif` = tâche en direct (boutons d'accord actifs).
// Les lignes qui se suivent sont regroupées pour rester serrées, comme dans un terminal.
function creerRenduCowork(conteneur, interactif) {
  let groupe = null;
  let derniere = null; // ligne « action » qui recevra son résultat
  let accordOuvert = null; // boutons d'une demande d'accord encore sans réponse
  const ajouterLigne = (ligne) => {
    if (!groupe || conteneur.lastElementChild !== groupe) {
      groupe = element("div", "groupe-etapes");
      conteneur.append(groupe);
    }
    groupe.append(ligne);
  };
  const ajouterBilan = (bilan) => {
    if (!bilanVide(bilan)) conteneur.append(carteBilan(bilan));
  };
  return (ev) => {
    if (ev.type === "statut") return;
    if (ev.type === "processus") {
      if (interactif && ev.liste) dessinerProcessus(ev.liste);
      return;
    }
    // La tâche avance : une demande restée ouverte a été tranchée ailleurs (API, autre fenêtre).
    if (accordOuvert?.isConnected) accordOuvert.replaceWith(element("div", "accord-decision", "Décision prise."));
    accordOuvert = null;
    if (ev.type === "tour") {
      ajouterLigne(element("div", "etape-tour", detailTour(ev)));
    } else if (ev.type === "action") {
      derniere = ligneEtape(ev, interactif);
      ajouterLigne(derniere);
    } else if (ev.type === "resultat") {
      if (derniere) ajouterResultat(derniere, ev);
    } else if (ev.type === "saute") {
      ajouterLigne(ligneSautee(ev));
    } else if (ev.type === "plan") {
      const carte = cartePlanCourante(conteneur);
      if (carte) remplirPlan(carte, ev.etapes);
      else {
        const nouvelle = element("div", "carte-plan");
        remplirPlan(nouvelle, ev.etapes);
        conteneur.append(nouvelle);
      }
    } else if (ev.type === "demande") {
      if (derniere) marquerEtape(derniere, "decision");
      const carte = carteDemande(ev, derniere?.dataset.detail ?? "", interactif);
      conteneur.append(carte);
      accordOuvert = carte.querySelector(".accord-actions");
    } else if (ev.type === "erreur_format") {
      ajouterLigne(noteFormat(ev));
    } else if (ev.type === "question") {
      conteneur.append(carteQuestion(ev, interactif));
    } else if (ev.type === "termine") {
      conteneur.append(bulle({ role: "gemini", texte: ev.resume.replace(/^TERMINÉ\s*:\s*/, ""), modele: null, niveau: null, duree: null }));
      ajouterBilan(ev.bilan);
    } else {
      if (ev.type === "refus" && derniere) marquerEtape(derniere, "ko");
      const point = ["autorise", "erreur_gemini", "relance_fin"].includes(ev.type) ? "decision" : ev.type === "relais" ? "" : "ko";
      ajouterLigne(noteEtape(ev, point));
      if (FIN_DE_TACHE.includes(ev.type)) ajouterBilan(ev.bilan);
    }
    defilerEnBas();
  };
}

async function envoyerCowork(texte) {
  if (!etat.dossier) {
    signaler("Choisis d'abord un dossier de travail", ROUGE);
    return;
  }
  etat.occupe = true;
  $("form-saisie").classList.add("occupe");
  $("saisie").value = "";
  ajusterSaisie();
  const fil = $("fil");
  fil.querySelector(".vide-discussion")?.remove();
  fil.append(bulle({ role: "toi", texte }));
  if (!etat.courante) $("titre-conversation").textContent = titreDepuis(texte);
  defilerEnBas();
  signaler("Cowork travaille…", ORANGE);
  try {
    if (!etat.courante) {
      const conversation = await appeler("POST", "/api/conversations", {
        mode: "cowork",
        dossier: etat.dossier,
        modele: etat.modele,
        niveau: etat.niveau,
        fournisseur: etat.fournisseur,
      });
      etat.courante = conversation.id;
    }
    await appeler("POST", `/api/cowork/${etat.courante}/messages`, { texte });
  } catch (e) {
    fil.append(bulle({ role: "erreur", texte: e.message }));
    $("saisie").value = texte; // pour pouvoir le renvoyer
    ajusterSaisie();
    signaler(e.message === "Agent First n'est pas démarré." ? "Agent First arrêté" : "Erreur", ROUGE);
    finirCowork();
    return;
  }
  ecouterFlux(etat.courante);
}

// Suit une tâche en direct. Rouvrir une conversation dont la tâche tourne rejoue ses étapes (depuis 0).
function ecouterFlux(identifiant, depuis = 0) {
  etat.flux?.close();
  const ajouter = creerRenduCowork($("fil"), true);
  etat.tache = identifiant;
  etat.occupe = true;
  $("form-saisie").classList.add("occupe");
  montrerArret(true);
  chargerConversations(); // la conversation apparaît tout de suite, avec son point « en cours »
  let actions = 0;
  const source = new EventSource(`/api/cowork/${identifiant}/flux?depuis=${depuis}`);
  etat.flux = source;
  source.onmessage = (message) => {
    const ev = JSON.parse(message.data);
    if (etat.courante === identifiant) ajouter(ev); // seulement si la conversation est encore affichée
    if (ev.type === "action") actions += 1;
    if (FIN_DE_TACHE.includes(ev.type)) {
      source.close();
      if (etat.courante === identifiant) {
        // une étape restée sans résultat (tâche arrêtée) ne doit plus avoir l'air de tourner
        $("fil").querySelectorAll(".point-etat.attente").forEach((p) => (p.className = "point-etat"));
      }
      finirCowork();
      if (ev.type === "erreur" && /est bloqué/.test(ev.corps)) chargerModes();
      if (ev.type === "termine") signaler(`${libelle()} prêt`, VERT);
      else if (ev.type === "question") {
        signaler(`${libelle()} attend ta réponse`, ORANGE);
        if (etat.courante === identifiant) $("saisie").focus();
      } else signaler(libelleEtape(ev).titre, ROUGE);
    } else if (ev.type === "statut") {
      if (ev.statut === "waiting_approval") signaler("En attente de ta décision", ORANGE);
      if (ev.statut === "queued") signaler(`En file d'attente : ${libelle()} termine une autre demande…`, ORANGE);
    } else if (ev.type !== "processus" && ev.type !== "demande") {
      signaler(`Cowork travaille… ${actions} action${actions > 1 ? "s" : ""}`, ORANGE);
    }
  };
  source.onerror = () => {
    source.close(); // pas de reconnexion automatique
    if (etat.tache === identifiant) {
      finirCowork();
      signaler("Flux interrompu (Agent First arrêté ?)", ROUGE);
    }
  };
}

function finirCowork() {
  etat.occupe = false;
  etat.tache = null;
  etat.flux = null;
  $("form-saisie").classList.remove("occupe");
  $("arreter").hidden = true;
  chargerConversations();
  if (etat.mode === "cowork" && etat.courante) chargerProcessus(etat.courante); // les serveurs lancés restent affichés
}

async function arreterTache() {
  if (!etat.tache && etat.envoi) {
    try {
      await appeler("POST", `/api/conversations/${etat.envoi}/arreter`);
      signaler("Arrêt demandé…", ORANGE);
    } catch (e) {
      signaler(e.message, ROUGE);
    }
    return;
  }
  if (!etat.tache) return;
  try {
    await appeler("POST", `/api/cowork/${etat.tache}/arreter`);
    signaler("Arrêt demandé (après l'étape en cours)…", ORANGE);
  } catch (e) {
    signaler(e.message, ROUGE);
  }
}

// Processus lancés par Cowork (serveurs…) : une pastille par processus actif dans l'en-tête.
function dessinerProcessus(liste) {
  const zone = $("processus");
  const actifs = (liste ?? []).filter((p) => p.actif);
  zone.replaceChildren(
    ...actifs.map((p) => {
      const pilule = element("span", "pilule-processus");
      pilule.title = `${p.commande}\nlancé il y a ${formaterDuree((Date.now() - new Date(p.depuis)) / 1000)}`;
      const arreter = element("button", "pilule-arreter", "Arrêter");
      arreter.type = "button";
      arreter.addEventListener("click", () => arreterProcessus(p.id));
      pilule.append(element("span", "point-processus"), element("span", "pilule-commande", `#${p.id} ${p.commande}`), arreter);
      return pilule;
    }),
  );
  zone.hidden = !actifs.length;
}

async function chargerProcessus(identifiant) {
  try {
    const { processus } = await appeler("GET", `/api/cowork/${identifiant}/processus`);
    if (etat.courante === identifiant) dessinerProcessus(processus);
  } catch {
    // Agent First injoignable : l'en-tête reste vide
  }
}

async function arreterProcessus(numero) {
  try {
    const r = await appeler("POST", `/api/cowork/${etat.courante}/processus/${numero}/arreter`);
    dessinerProcessus(r.processus);
    signaler(r.ok ? `Processus #${numero} arrêté` : r.corps, r.ok ? VERT : ROUGE);
  } catch (e) {
    signaler(e.message, ROUGE);
  }
}

// Tâches qui tournent ailleurs (API réseau, autre conversation) : marque dans la barre et bandeau
// si l'une attend un accord.
function ecouterEvenements() {
  const source = new EventSource("/api/evenements");
  source.onmessage = (message) => {
    const ev = JSON.parse(message.data);
    if (ev.type === "processus") {
      if (ev.liste && ev.conversation_id === etat.courante) dessinerProcessus(ev.liste);
      return;
    }
    const id = ev.conversation_id;
    const avant = `${etat.actives.has(id)}${etat.attentes.has(id)}`;
    if (ev.statut === "waiting_approval") etat.attentes.add(id);
    else etat.attentes.delete(id);
    if (["queued", "running", "waiting_approval"].includes(ev.statut)) etat.actives.add(id);
    else etat.actives.delete(id);
    if (avant !== `${etat.actives.has(id)}${etat.attentes.has(id)}`) chargerConversations();
    dessinerBandeau();
  };
  // En cas de coupure, EventSource se reconnecte tout seul.
}

function dessinerBandeau() {
  const ailleurs = [...etat.attentes].find((id) => !(id === etat.tache && id === etat.courante));
  $("bandeau-accord").hidden = !ailleurs;
  $("bandeau-accord").dataset.conversation = ailleurs ?? "";
}

function dessinerMode() {
  $("modes").querySelectorAll("button").forEach((b) => b.classList.toggle("actif", b.dataset.mode === etat.mode));
  $("choisir-dossier").hidden = etat.mode !== "cowork";
  $("nom-dossier").textContent = etat.dossier ? cheminCourt(etat.dossier) : "Choisir un dossier";
  $("choisir-dossier").title = etat.dossier ? `${etat.dossier} (cliquer pour changer)` : "Choisir le dossier de travail";
  $("joindre").hidden = etat.mode === "cowork";
  $("exporter").hidden = !etat.courante;
  if (etat.mode === "cowork") viderPieces();
  dessinerOutil();
}

function choisirMode(mode) {
  if (etat.occupe) {
    signaler("Attends la fin de la tâche en cours", ORANGE);
    return;
  }
  if (mode === etat.mode && !etat.courante) return;
  etat.mode = mode;
  nouvelleConversation();
}

async function choisirDossier() {
  if (etat.occupe) return;
  try {
    signaler("Choisis le dossier dans la fenêtre Windows…", ORANGE);
    const { dossier } = await appeler("POST", "/api/dossiers/choisir");
    if (!dossier) {
      signaler("Aucun dossier choisi", GRIS);
      return;
    }
    ecrire(CLE_DOSSIER, dossier);
    if (etat.courante && dossier !== etat.dossier) {
      nouvelleConversation(); // un autre dossier = une nouvelle conversation
    } else {
      etat.dossier = dossier;
      dessinerMode();
      $("fil").querySelector(".vide-discussion")?.replaceWith(accueilDiscussion());
    }
    signaler("Dossier de travail choisi", VERT);
  } catch (e) {
    signaler(e.message, ROUGE);
  }
}

// ---------- accueil / historique ----------

async function chargerAccueil() {
  const recherche = $("recherche-historique").value.trim();
  try {
    const [statistiques, conversations] = await Promise.all([
      appeler("GET", `/api/statistiques?${new URLSearchParams({ periode: etat.periode })}`),
      appeler("GET", `/api/conversations?${new URLSearchParams({ recherche, periode: etat.periode })}`),
    ]);
    dessinerCartes(statistiques);
    dessinerLignes(conversations, recherche);
    chargerGalerie();
  } catch (e) {
    signaler(e.message, ROUGE);
  }
}

function dessinerCartes(s) {
  const cartes = [
    ["Conversations", "sur la période", String(s.conversations)],
    ["Messages", "envoyés aux assistants", String(s.messages)],
    // Un nom de modèle est plus long qu'un nombre : écrit plus petit pour tenir dans la carte.
    ["Modèle favori", "le plus utilisé", s.modele_favori ?? "—", "texte"],
    ["Temps moyen", "par réponse", s.temps_moyen == null ? "—" : formaterDuree(s.temps_moyen)],
    ["Médias créés", "images, vidéos, sons", String(s.medias ?? 0)],
  ];
  $("cartes").replaceChildren(
    ...cartes.map(([titre, sousTitre, valeur, style = ""]) => {
      const carte = element("div", "carte");
      carte.append(element("div", "carte-titre", titre), element("div", `nombre ${style}`, valeur), element("div", "carte-sous", sousTitre));
      return carte;
    }),
  );
}

async function chargerGalerie() {
  let medias;
  try {
    medias = await appeler("GET", `/api/medias?${new URLSearchParams({ limite: 24, ...(etat.filtreMedias ? { type: etat.filtreMedias } : {}) })}`);
  } catch {
    return;
  }
  const panneau = $("panneau-medias");
  panneau.hidden = !medias.length && !etat.filtreMedias;
  $("galerie").replaceChildren(
    ...(medias.length ? medias.map(tuileMedia) : [element("p", "vide", "Aucun média de ce type pour l'instant.")]),
  );
}

// Une tuile de la galerie : l'image (visionneuse au clic), ou vidéo/son (ouvre sa conversation).
function tuileMedia(m) {
  const tuile = element("button", `tuile tuile-${m.type}`);
  tuile.type = "button";
  tuile.title = `${m.titre || "Sans titre"} · ${formaterDate(m.cree_le)}`;
  if (m.type === "image") {
    const image = element("img");
    image.src = `/api/medias/${m.id}`;
    image.alt = m.description || m.titre || "Image créée";
    image.loading = "lazy";
    tuile.append(image);
    tuile.addEventListener("click", () => ouvrirVisionneuse(m));
  } else {
    tuile.append(icone(m.type === "video" ? "i-video" : "i-musique"), element("span", "tuile-titre", m.titre || "Sans titre"));
    tuile.addEventListener("click", () => ouvrirConversation(m.conversation_id));
  }
  return tuile;
}

function dessinerLignes(conversations, recherche) {
  const lignes = $("lignes-historique");
  if (!conversations.length) {
    lignes.replaceChildren(
      element("p", "vide", recherche ? "Aucune conversation ne correspond." : "Aucune conversation sur cette période."),
    );
    return;
  }
  lignes.replaceChildren(
    ...conversations.map((c) => {
      const ligne = element("div", "ligne");
      const ouvrir = element("button", "ligne-titre", c.titre || "Sans titre");
      ouvrir.type = "button";
      ouvrir.title = c.titre;
      ouvrir.addEventListener("click", () => ouvrirConversation(c.id));
      const nombre = `${c.nb_messages} message${c.nb_messages > 1 ? "s" : ""}`;
      const assistant = c.fournisseur && c.fournisseur !== "gemini" ? libelle(c.fournisseur) : null;
      const infos = element("span", "ligne-infos", [assistant, c.modele, nombre, formaterDate(c.modifie_le)].filter(Boolean).join(" · "));
      const supprimer = element("button", "icone");
      supprimer.type = "button";
      supprimer.title = "Retirer de l'historique";
      supprimer.setAttribute("aria-label", `Retirer « ${c.titre} » de l'historique`);
      supprimer.append(icone("i-corbeille"));
      supprimer.addEventListener("click", () => supprimerConversation(c));
      const mode = (c.mode === "cowork" ? "cowork" : "chat") + (c.source === "api" ? " · api" : "");
      ligne.append(ouvrir, element("span", "ligne-mode", mode), infos, supprimer);
      return ligne;
    }),
  );
}

async function supprimerConversation(c) {
  if (!confirm(`Retirer « ${c.titre} » de l'historique de l'app ?\nLa conversation reste sur le site de ${libelle(c.fournisseur ?? "gemini")}.`)) return;
  try {
    await appeler("DELETE", `/api/conversations/${c.id}`);
    if (etat.courante === c.id) etat.courante = null;
    chargerAccueil();
    chargerConversations();
  } catch (e) {
    signaler(e.message, ROUGE);
  }
}

// ---------- paramètres ----------

function remplir(select, options, valeur) {
  select.replaceChildren(...options.map((o) => new Option(`${o.nom} — ${o.description}`, o.nom, false, o.nom === valeur)));
}

const SEPARATEUR = "::"; // valeur d'une option du modèle par défaut : « chatgpt::Thinking »

// Le modèle par défaut, rangé par assistant (un groupe par assistant).
function remplirModeles(select, defaut) {
  const actif = (liste) => liste.find((o) => o.actif)?.nom ?? null;
  const fournisseurs = etat.fournisseurs.length ? etat.fournisseurs : [{ ...fournisseurCourant(), modeles: etat.modes.modeles }];
  const voulu = defaut.fournisseur ?? "gemini";
  select.replaceChildren(...fournisseurs.map((f) => {
    const groupe = document.createElement("optgroup");
    groupe.label = f.libelle;
    const modeles = f.modeles.length ? f.modeles : [{ nom: null, description: "le modèle déjà choisi sur le site" }];
    const choisi = f.nom === voulu ? defaut.modele ?? actif(f.modeles) : undefined;
    groupe.append(...modeles.map((o) => new Option(
      `${f.libelle} · ${o.nom ?? "par défaut"}${o.description ? ` — ${o.description}` : ""}`,
      `${f.nom}${SEPARATEUR}${o.nom ?? ""}`, false, f.nom === voulu && (o.nom ?? null) === (choisi ?? null),
    )));
    return groupe;
  }));
}

function niveauxPar(nom) {
  return (etat.fournisseurs.find((f) => f.nom === nom) ?? (nom === etat.fournisseur ? etat.modes : null))?.niveaux ?? [];
}

function ouvrirParametres() {
  const defaut = lire(CLE_DEFAUT, {});
  const actif = (liste) => liste.find((o) => o.actif)?.nom;
  remplirModeles($("defaut-modele"), defaut);
  const niveaux = niveauxPar(defaut.fournisseur ?? "gemini");
  remplir($("defaut-niveau"), niveaux, defaut.niveau ?? actif(niveaux));
  $("defaut-niveau").parentElement.hidden = !niveaux.length;
  const s = etat.serveur;
  const lignes = [
    ["Agent First", s ? ["prêt", VERT] : ["arrêté", ROUGE]],
    ["Chrome dédié", !s ? ["inconnu", GRIS] : s.chrome ? ["ouvert", VERT] : ["s'ouvrira au premier message", GRIS]],
    ["Compte Google (Gemini)", !s ? ["inconnu", GRIS] : ETATS_GOOGLE[String(s.google)]],
    ...etat.fournisseurs.filter((f) => f.nom !== "gemini").map((f) => [f.libelle, etatConnexion(f.nom)]),
  ];
  $("etats").replaceChildren(
    ...lignes.map(([nom, [texte, couleur]]) => {
      const ligne = element("div", "etat");
      const point = element("span", "point");
      point.style.background = couleur;
      ligne.append(point, element("span", null, `${nom} · ${texte}`));
      return ligne;
    }),
  );
  dessinerApiReseau();
  dessinerAssistants();
  $("parametres").showModal();
}

// Paramètres : la redondance et l'ordre dans lequel les assistants prennent le relais.
async function dessinerAssistants() {
  const zone = $("assistants");
  if (etat.fournisseurs.length < 2) {
    zone.replaceChildren();
    return;
  }
  try {
    etat.reglagesApp = await appeler("GET", "/api/reglages");
  } catch {
    zone.replaceChildren();
    return;
  }
  const { redondance, ordre } = etat.reglagesApp;
  const interrupteur = element("label", "interrupteur");
  const caseRedondance = element("input");
  caseRedondance.type = "checkbox";
  caseRedondance.id = "redondance";
  caseRedondance.checked = redondance;
  caseRedondance.setAttribute("role", "switch");
  interrupteur.append(caseRedondance, element("span", "interrupteur-texte", "Redondance"));
  caseRedondance.addEventListener("change", () => enregistrerReglages({ redondance: caseRedondance.checked }));
  const explication = element("p", "note", redondance
    ? "Si un assistant est saturé, n'a plus de crédits ou ne répond pas, le suivant de la liste reprend la conversation tout seul."
    : "Désactivée : si un assistant est saturé ou n'a plus de crédits, Agent First te propose les autres et tu choisis.");
  const liste = element("ol", "ordre-assistants");
  ordre.forEach((nom, rang) => {
    const ligne = element("li");
    const point = element("span", "point");
    const [texte, couleur] = etatConnexion(nom);
    point.style.background = couleur;
    point.title = texte;
    const f = etat.fournisseurs.find((x) => x.nom === nom);
    const cree = (f?.outils ?? []).map((o) => OUTILS[o]?.nom.toLowerCase()).filter(Boolean);
    ligne.append(point, element("span", "ordre-nom", libelle(nom)), element("span", "ordre-info", cree.length ? cree.join(", ") : "texte"));
    for (const [sens, symbole, titre] of [[-1, "↑", "Monter"], [1, "↓", "Descendre"]]) {
      const bouton = element("button", "icone ordre-bouton", symbole);
      bouton.type = "button";
      bouton.title = `${titre} ${libelle(nom)}`;
      bouton.setAttribute("aria-label", bouton.title);
      bouton.disabled = rang + sens < 0 || rang + sens >= ordre.length;
      bouton.addEventListener("click", () => {
        const nouvel = ordre.slice();
        [nouvel[rang], nouvel[rang + sens]] = [nouvel[rang + sens], nouvel[rang]];
        enregistrerReglages({ ordre: nouvel });
      });
      ligne.append(bouton);
    }
    liste.append(ligne);
  });
  zone.replaceChildren(
    element("h3", null, "Assistants"),
    interrupteur,
    explication,
    liste,
    element("p", "note", "Ordre de relais. Connecte-toi une fois à chaque site dans la fenêtre Chrome dédiée (elle s'ouvre au premier message). Les médias passent seulement aux assistants qui savent les créer."),
  );
}

async function enregistrerReglages(changement) {
  try {
    etat.reglagesApp = await appeler("POST", "/api/reglages", changement);
    signaler("redondance" in changement ? `Redondance ${etat.reglagesApp.redondance ? "activée" : "désactivée"}` : "Ordre des assistants enregistré", VERT);
  } catch (e) {
    signaler(e.message, ROUGE);
  }
  if ($("parametres").open) dessinerAssistants();
}

async function dessinerApiReseau() {
  const zone = $("api-reseau");
  let infos;
  try {
    infos = await appeler("GET", "/api/api-reseau");
  } catch {
    zone.replaceChildren();
    return;
  }
  const titre = element("h3", null, "API réseau");
  if (!infos.active) {
    zone.replaceChildren(titre, element("p", "note", "Désactivée. Pour l'activer : API_ACTIVE = True dans config.py, puis redémarre Agent First."));
    return;
  }
  const regenerer = element("button", "bouton-secondaire", "Régénérer la clé");
  regenerer.type = "button";
  regenerer.addEventListener("click", async () => {
    if (!confirm("Créer une nouvelle clé ?\nLes programmes qui utilisent l'ancienne devront être mis à jour.")) return;
    try {
      await appeler("POST", "/api/api-reseau/cle");
      dessinerApiReseau();
      signaler("Nouvelle clé créée", VERT);
    } catch (e) {
      signaler(e.message, ROUGE);
    }
  });
  zone.replaceChildren(
    titre,
    ligneApi("Adresse", infos.adresse, infos.adresse),
    ligneApi("Clé", `••••••••${infos.cle.slice(-4)}`, infos.cle),
    element("p", "note", "Pour d'autres programmes, sur ce PC ou ton réseau : format OpenAI (/v1/chat/completions) et tâches Cowork (/v1/cowork), avec l'en-tête Authorization: Bearer <clé>. Exemples dans le README."),
    regenerer,
  );
}

function ligneApi(nom, affiche, aCopier) {
  const ligne = element("div", "ligne-api");
  const copier = element("button", "icone");
  copier.type = "button";
  copier.title = `Copier : ${nom.toLowerCase()}`;
  copier.setAttribute("aria-label", copier.title);
  copier.append(icone("i-copier"));
  copier.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(aCopier);
      signaler(`${nom} copiée`, VERT);
    } catch {
      signaler("Copie impossible", ROUGE);
    }
  });
  ligne.append(element("span", "ligne-api-nom", nom), element("code", null, affiche), copier);
  return ligne;
}

function sauverDefaut(e) {
  const [fournisseur, modele] = $("defaut-modele").value.split(SEPARATEUR);
  if (e?.target === $("defaut-modele")) {
    // un autre assistant : ses propres niveaux (Gemini seulement)
    const niveaux = niveauxPar(fournisseur);
    remplir($("defaut-niveau"), niveaux, niveaux.find((o) => o.actif)?.nom);
    $("defaut-niveau").parentElement.hidden = !niveaux.length;
  }
  ecrire(CLE_DEFAUT, { fournisseur, modele: modele || null, niveau: $("defaut-niveau").parentElement.hidden ? null : $("defaut-niveau").value || null });
  signaler("Réglages par défaut enregistrés", VERT);
}

// ---------- démarrage ----------

function brancherEvenements() {
  $("nouvelle").addEventListener("click", nouvelleConversation);
  $("aller-accueil").addEventListener("click", () => {
    afficherVue("accueil");
    chargerAccueil();
  });
  $("aller-historique").addEventListener("click", async () => {
    afficherVue("accueil");
    await chargerAccueil();
    $("panneau-historique").scrollIntoView({ behavior: "smooth" });
  });
  $("ouvrir-parametres").addEventListener("click", ouvrirParametres);
  $("modes").addEventListener("click", (e) => {
    const bouton = e.target.closest("[data-mode]");
    if (bouton) choisirMode(bouton.dataset.mode);
  });
  $("choisir-dossier").addEventListener("click", choisirDossier);
  $("arreter").addEventListener("click", arreterTache);
  $("bandeau-ouvrir").addEventListener("click", () => {
    const id = $("bandeau-accord").dataset.conversation;
    if (id) ouvrirConversation(id);
  });
  $("replier").addEventListener("click", basculerBarre);
  $("deplier").addEventListener("click", basculerBarre);
  $("bouton-modele").addEventListener("click", () => basculerMenu("bouton-modele"));
  $("bouton-niveau").addEventListener("click", () => basculerMenu("bouton-niveau"));
  $("bouton-outil").addEventListener("click", () => basculerMenu("bouton-outil"));
  $("joindre").addEventListener("click", () => $("fichiers").click());
  $("fichiers").addEventListener("change", (e) => {
    ajouterPieces(e.target.files);
    e.target.value = ""; // le même fichier peut être rejoint plus tard
  });
  $("saisie").addEventListener("paste", (e) => {
    if (e.clipboardData?.files?.length) ajouterPieces(e.clipboardData.files); // une capture d'écran collée
  });
  // Glisser-déposer des fichiers n'importe où sur la discussion.
  const discussion = $("vue-discussion");
  discussion.addEventListener("dragover", (e) => {
    if (![...(e.dataTransfer?.types ?? [])].includes("Files")) return;
    e.preventDefault();
    $("form-saisie").classList.add("depot");
  });
  discussion.addEventListener("dragleave", (e) => {
    if (!discussion.contains(e.relatedTarget)) $("form-saisie").classList.remove("depot");
  });
  discussion.addEventListener("drop", (e) => {
    if (!e.dataTransfer?.files?.length) return;
    e.preventDefault();
    $("form-saisie").classList.remove("depot");
    ajouterPieces(e.dataTransfer.files);
  });
  $("exporter").addEventListener("click", () => {
    if (etat.courante) window.location.href = `/api/conversations/${etat.courante}/export`;
  });
  $("filtre-medias").addEventListener("click", (e) => {
    const bouton = e.target.closest("[data-type]");
    if (!bouton) return;
    etat.filtreMedias = bouton.dataset.type;
    $("filtre-medias").querySelectorAll("button").forEach((b) => b.classList.toggle("actif", b === bouton));
    chargerGalerie();
  });
  $("visionneuse").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) $("visionneuse").close(); // clic à côté de l'image
  });
  $("form-saisie").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) $("saisie").focus(); // un clic dans le cadre vide vise le texte
  });
  $("form-saisie").addEventListener("submit", (e) => {
    e.preventDefault();
    envoyer();
  });
  $("saisie").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      envoyer();
    }
  });
  $("saisie").addEventListener("input", ajusterSaisie);
  let attente;
  const plusTard = (action) => {
    clearTimeout(attente);
    attente = setTimeout(action, 250);
  };
  $("recherche").addEventListener("input", () => plusTard(chargerConversations));
  $("recherche-historique").addEventListener("input", () => plusTard(chargerAccueil));
  $("form-historique").addEventListener("submit", (e) => {
    e.preventDefault();
    chargerAccueil();
  });
  $("periodes").addEventListener("click", (e) => {
    const bouton = e.target.closest("[data-periode]");
    if (!bouton) return;
    etat.periode = bouton.dataset.periode;
    $("periodes").querySelectorAll("button").forEach((b) => b.classList.toggle("actif", b === bouton));
    chargerAccueil();
  });
  $("defaut-modele").addEventListener("change", sauverDefaut);
  $("defaut-niveau").addEventListener("change", sauverDefaut);
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".menu-reglage")) fermerMenus();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") fermerMenus();
    if (e.key === "/" && !e.target.closest("input, textarea, select")) {
      e.preventDefault();
      $("recherche").focus();
    }
  });
}

async function demarrer() {
  if (lire(CLE_BARRE, false)) document.body.classList.add("barre-repliee");
  brancherEvenements();
  dessinerMode();
  afficherVue("accueil");
  signaler("Connexion…", GRIS);
  await verifierEtat();
  chargerConversations();
  chargerAccueil();
  ecouterEvenements();
  const defaut = lire(CLE_DEFAUT, {});
  await chargerModes();
  appliquerFournisseur(fournisseurParDefaut(defaut), defaut.modele, defaut.niveau);
  setInterval(() => {
    if (!etat.occupe) verifierEtat();
  }, 30000);
}

demarrer();
