// agent.first — état, affichage et événements de l'app.
import { appeler } from "./api.js";
import { cheminCourt, choixDisponible, formaterDate, formaterDuree, groupesParDate, limiteOption, metaMessage, titreDepuis } from "./outils.js";
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
const ETATS_GOOGLE = {
  true: ["connecté", VERT],
  false: ["non connecté", ROUGE],
  null: ["à vérifier", GRIS],
};

const etat = {
  modes: { modeles: [], niveaux: [] },
  modele: null,
  niveau: null,
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
    if (!etat.occupe) signaler("Gemini prêt", VERT);
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
    etat.modes = await appeler("GET", "/api/modeles");
  } catch (e) {
    signaler(e.message, ROUGE);
  }
  choisirReglages(etat.modele, etat.niveau);
}

function choisirReglages(modele, niveau) {
  const { modeles, niveaux } = etat.modes;
  // un choix bloqué par la limite du compte est remplacé par un choix disponible
  etat.modele = choixDisponible(modeles, modele);
  etat.niveau = choixDisponible(niveaux, niveau);
  dessinerReglages();
}

function optionsMenu(liste, choisi, choisir) {
  return liste.map((o) => {
    const option = element("button", "option");
    option.type = "button";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(o.nom === choisi));
    option.append(element("span", "option-nom", o.nom), element("span", "option-desc", o.description));
    const limite = limiteOption(o);
    if (limite) {
      option.classList.add("bloquee"); // Gemini refusera ce choix jusqu'à la réinitialisation
      option.title = `Bloqué par la limite de ton compte Gemini jusqu'au ${limite}`;
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
  $("nom-modele").textContent = etat.modele ?? "Modèle";
  $("nom-niveau").textContent = etat.niveau ? `Réflexion ${etat.niveau}` : "Réflexion";
  $("menu-modeles").replaceChildren(...optionsMenu(etat.modes.modeles, etat.modele, (nom) => (etat.modele = nom)));
  $("menu-niveaux").replaceChildren(...optionsMenu(etat.modes.niveaux, etat.niveau, (nom) => (etat.niveau = nom)));
  $("bouton-niveau").parentElement.hidden = !etat.modes.niveaux.length;
}

// bouton → menu qu'il ouvre, au-dessus de la zone de saisie
const MENUS = { "bouton-modele": "menu-modeles", "bouton-niveau": "menu-niveaux" };

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
      bouton.title = [c.mode === "cowork" ? "Cowork" : null, c.source === "api" ? "API" : null, c.titre].filter(Boolean).join(" · ");
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

function bulle(message) {
  if (message.role === "toi") {
    const b = element("div", "bulle toi");
    b.append(element("div", "texte-toi", message.texte));
    return b;
  }
  if (message.role === "erreur") {
    return element("div", "bulle erreur", `Erreur : ${message.texte}`);
  }
  // Réponse de Gemini : du texte, sans carte ; le modèle et la durée en dessous, en petit.
  const carte = element("article", "bulle gemini");
  const contenu = element("div", "markdown");
  if (message.html) {
    contenu.innerHTML = message.html; // déjà nettoyé par Agent First (nh3)
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
  pied.append(element("span", null, metaMessage(message)), copier);
  carte.append(contenu, pied);
  return carte;
}

function accueilDiscussion() {
  const bloc = element("div", "vide-discussion");
  if (etat.mode === "cowork") {
    bloc.append(element("h1", null, "Travaille avec Gemini sur ton PC"));
    const aide = element("p");
    if (etat.dossier) {
      aide.append(
        document.createTextNode("Gemini fait un plan, lit, crée et modifie des fichiers, lance des commandes et des serveurs dans "),
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
  bloc.append(
    element("h1", null, "Discute avec Gemini"),
    element("p", null, "Choisis le modèle et le niveau de réflexion sous la zone de saisie, puis pose ta question."),
  );
  return bloc;
}

function nouvelleConversation() {
  etat.courante = null;
  if (etat.mode === "cowork") etat.dossier = lire(CLE_DOSSIER, null);
  $("titre-conversation").textContent = "Nouvelle conversation";
  const defaut = lire(CLE_DEFAUT, {});
  choisirReglages(defaut.modele, defaut.niveau);
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
    etat.mode = conversation.mode ?? "chat";
    etat.dossier = conversation.dossier ?? null;
    $("titre-conversation").textContent = conversation.titre || "Conversation";
    choisirReglages(conversation.modele, conversation.niveau);
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

async function envoyer() {
  const texte = $("saisie").value.trim();
  if (!texte || etat.occupe) return;
  if (etat.mode === "cowork") return envoyerCowork(texte);
  etat.occupe = true;
  $("form-saisie").classList.add("occupe");
  $("saisie").value = "";
  ajusterSaisie();

  const fil = $("fil");
  fil.querySelector(".vide-discussion")?.remove();
  fil.append(bulle({ role: "toi", texte }));
  const attente = element("div", "bulle attente");
  const libelle = element("span", null, "Gemini réfléchit…");
  attente.append(element("span", "points"), libelle);
  fil.append(attente);
  defilerEnBas();
  if (!etat.courante) $("titre-conversation").textContent = titreDepuis(texte);

  const debut = Date.now();
  signaler("Gemini réfléchit…", ORANGE);
  const minuteur = setInterval(() => {
    const ecoule = `Gemini réfléchit… ${formaterDuree((Date.now() - debut) / 1000)}`;
    libelle.textContent = ecoule;
    signaler(ecoule, ORANGE);
  }, 1000);

  try {
    if (!etat.courante) {
      const conversation = await appeler("POST", "/api/conversations", { modele: etat.modele, niveau: etat.niveau });
      etat.courante = conversation.id;
    }
    const { message } = await appeler("POST", `/api/conversations/${etat.courante}/messages`, {
      texte,
      modele: etat.modele,
      niveau: etat.niveau,
    });
    attente.replaceWith(bulle(message));
    signaler("Gemini prêt", VERT);
    verifierEtat(); // Chrome et Google viennent de servir : l'état affiché se met à jour
  } catch (e) {
    attente.replaceWith(bulle({ role: "erreur", texte: e.message }));
    $("saisie").value = texte; // pour pouvoir le renvoyer
    ajusterSaisie();
    signaler(e.message === "Agent First n'est pas démarré." ? "Agent First arrêté" : "Erreur", ROUGE);
    verifierEtat(); // met à jour l'état du compte (la pastille garde l'erreur tant que l'envoi est en cours)
    if (/n'est pas proposé|est bloqué/.test(e.message)) chargerModes(); // menus à jour (choix bloqués)
  } finally {
    clearInterval(minuteur);
    etat.occupe = false;
    $("form-saisie").classList.remove("occupe");
    defilerEnBas();
    chargerConversations();
  }
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
      ajouterLigne(noteEtape(ev, ["autorise", "erreur_gemini", "relance_fin"].includes(ev.type) ? "decision" : "ko"));
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
  $("arreter").hidden = false;
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
      if (ev.type === "termine") signaler("Gemini prêt", VERT);
      else if (ev.type === "question") {
        signaler("Gemini attend ta réponse", ORANGE);
        if (etat.courante === identifiant) $("saisie").focus();
      } else signaler(libelleEtape(ev).titre, ROUGE);
    } else if (ev.type === "statut") {
      if (ev.statut === "waiting_approval") signaler("En attente de ta décision", ORANGE);
      if (ev.statut === "queued") signaler("En file d'attente : Gemini termine une autre demande…", ORANGE);
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
  $("saisie").placeholder = etat.mode === "cowork" ? "Décris une tâche à Cowork…" : "Demande à Gemini…";
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
  } catch (e) {
    signaler(e.message, ROUGE);
  }
}

function dessinerCartes(s) {
  const cartes = [
    ["Conversations", "sur la période", String(s.conversations)],
    ["Messages", "envoyés à Gemini", String(s.messages)],
    // Un nom de modèle est plus long qu'un nombre : écrit plus petit pour tenir dans la carte.
    ["Modèle favori", "le plus utilisé", s.modele_favori ?? "—", "texte"],
    ["Temps moyen", "par réponse", s.temps_moyen == null ? "—" : formaterDuree(s.temps_moyen)],
  ];
  $("cartes").replaceChildren(
    ...cartes.map(([titre, sousTitre, valeur, style = ""]) => {
      const carte = element("div", "carte");
      carte.append(element("div", "carte-titre", titre), element("div", `nombre ${style}`, valeur), element("div", "carte-sous", sousTitre));
      return carte;
    }),
  );
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
      const infos = element("span", "ligne-infos", [c.modele, nombre, formaterDate(c.modifie_le)].filter(Boolean).join(" · "));
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
  if (!confirm(`Retirer « ${c.titre} » de l'historique de l'app ?\nLa conversation reste dans Gemini.`)) return;
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

function ouvrirParametres() {
  const defaut = lire(CLE_DEFAUT, {});
  const actif = (liste) => liste.find((o) => o.actif)?.nom;
  remplir($("defaut-modele"), etat.modes.modeles, defaut.modele ?? actif(etat.modes.modeles));
  remplir($("defaut-niveau"), etat.modes.niveaux, defaut.niveau ?? actif(etat.modes.niveaux));
  const s = etat.serveur;
  const lignes = [
    ["Agent First", s ? ["prêt", VERT] : ["arrêté", ROUGE]],
    ["Chrome dédié", !s ? ["inconnu", GRIS] : s.chrome ? ["ouvert", VERT] : ["s'ouvrira au premier message", GRIS]],
    ["Compte Google", !s ? ["inconnu", GRIS] : ETATS_GOOGLE[String(s.google)]],
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
  $("parametres").showModal();
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

function sauverDefaut() {
  ecrire(CLE_DEFAUT, { modele: $("defaut-modele").value, niveau: $("defaut-niveau").value });
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
  await chargerModes();
  const defaut = lire(CLE_DEFAUT, {});
  choisirReglages(defaut.modele, defaut.niveau);
  setInterval(() => {
    if (!etat.occupe) verifierEtat();
  }, 30000);
}

demarrer();
