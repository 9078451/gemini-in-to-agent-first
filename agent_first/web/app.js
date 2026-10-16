// agent.first — état, affichage et événements de l'app.
import { appeler } from "./api.js";
import { formaterDate, formaterDuree, groupesParDate, metaMessage, titreDepuis } from "./outils.js";
import { libelleEtape } from "./outils_cowork.js";

const $ = (id) => document.getElementById(id);
const CLE_DEFAUT = "agent.first.defaut";
const CLE_BARRE = "agent.first.barre-repliee";
const CLE_DOSSIER = "agent.first.dossier";
const FIN_DE_TACHE = ["termine", "limite", "arret", "erreur"];
const VERT = "var(--vert)";
const ORANGE = "var(--orange)";
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
  tache: null, // conversation dont une tâche Cowork tourne
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
  saisie.style.height = `${Math.min(saisie.scrollHeight, 200)}px`;
}

// ---------- état d'Agent First et de Gemini ----------

async function verifierEtat() {
  try {
    etat.serveur = await appeler("GET", "/api/etat");
    const [texte, couleur] = ETATS_GOOGLE[String(etat.serveur.google)];
    $("etat-google").textContent = texte;
    $("etat-google").style.color = couleur;
    if (!etat.occupe) signaler("Gemini prêt", VERT);
  } catch {
    etat.serveur = null;
    $("etat-google").textContent = "inconnu";
    $("etat-google").style.color = GRIS;
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
  const existe = (liste, nom) => liste.some((o) => o.nom === nom);
  const actif = (liste) => liste.find((o) => o.actif)?.nom ?? liste[0]?.nom ?? null;
  etat.modele = existe(modeles, modele) ? modele : actif(modeles);
  etat.niveau = existe(niveaux, niveau) ? niveau : actif(niveaux);
  dessinerReglages();
}

function dessinerReglages() {
  $("nom-modele").textContent = etat.modele ?? "Modèle";
  $("menu-modeles").replaceChildren(
    ...etat.modes.modeles.map((m) => {
      const option = element("button", "option");
      option.type = "button";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(m.nom === etat.modele));
      option.append(element("span", "option-nom", m.nom), element("span", "option-desc", m.description));
      option.addEventListener("click", () => {
        etat.modele = m.nom;
        fermerMenu();
        dessinerReglages();
      });
      return option;
    }),
  );
  $("niveaux").hidden = !etat.modes.niveaux.length;
  $("niveaux").replaceChildren(
    ...etat.modes.niveaux.map((n) => {
      const bouton = element("button", n.nom === etat.niveau ? "actif" : "", n.nom);
      bouton.type = "button";
      bouton.title = n.description;
      bouton.setAttribute("role", "radio");
      bouton.setAttribute("aria-checked", String(n.nom === etat.niveau));
      bouton.addEventListener("click", () => {
        etat.niveau = n.nom;
        dessinerReglages();
      });
      return bouton;
    }),
  );
}

function basculerMenu() {
  const menu = $("menu-modeles");
  menu.hidden = !menu.hidden;
  $("bouton-modele").setAttribute("aria-expanded", String(!menu.hidden));
}

function fermerMenu() {
  $("menu-modeles").hidden = true;
  $("bouton-modele").setAttribute("aria-expanded", "false");
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
      const bouton = element("button", "conversation", c.titre || "Sans titre");
      bouton.type = "button";
      bouton.title = c.titre;
      bouton.classList.toggle("actif", c.id === etat.courante);
      bouton.classList.toggle("cowork", c.mode === "cowork");
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
    const b = element("div", "bulle erreur");
    const meta = element("div", "meta");
    meta.append(element("span", "point"), document.createTextNode("Erreur"));
    b.append(meta, element("div", null, message.texte));
    return b;
  }
  const carte = element("article", "bulle gemini");
  const meta = element("div", "meta");
  meta.append(element("span", "point"), document.createTextNode(metaMessage(message)));
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
  const actions = element("div", "actions");
  actions.append(copier);
  carte.append(meta, contenu, actions);
  return carte;
}

function accueilDiscussion() {
  const bloc = element("div", "vide-discussion");
  if (etat.mode === "cowork") {
    const titre = element("h1", null, "Travaille avec ");
    titre.append(element("span", "accent", "Gemini"), document.createTextNode(" sur ton PC"));
    const aide = etat.dossier
      ? "Décris la tâche : Gemini lira, créera et modifiera des fichiers et lancera des commandes dans ce dossier."
      : "Choisis d'abord le dossier de travail, puis décris la tâche.";
    bloc.append(titre, element("p", null, aide));
    return bloc;
  }
  const titre = element("h1", null, "Discute avec ");
  titre.append(element("span", "accent", "Gemini"));
  bloc.append(titre, element("p", null, "Choisis un modèle et un niveau de réflexion, puis pose ta question."));
  return bloc;
}

function nouvelleConversation() {
  etat.courante = null;
  if (etat.mode === "cowork") etat.dossier = lire(CLE_DOSSIER, null);
  $("titre-conversation").textContent = "Nouvelle conversation";
  const defaut = lire(CLE_DEFAUT, {});
  choisirReglages(defaut.modele, defaut.niveau);
  dessinerMode();
  $("fil").replaceChildren(accueilDiscussion());
  afficherVue("discussion");
  chargerConversations();
  $("saisie").focus();
}

async function ouvrirConversation(identifiant) {
  try {
    const { conversation, messages } = await appeler("GET", `/api/conversations/${identifiant}`);
    etat.courante = conversation.id;
    etat.mode = conversation.mode ?? "chat";
    etat.dossier = conversation.dossier ?? null;
    $("titre-conversation").textContent = conversation.titre || "Conversation";
    choisirReglages(conversation.modele, conversation.niveau);
    dessinerMode();
    const fil = $("fil");
    fil.replaceChildren();
    const ajouter = creerRenduCowork(fil, false);
    for (const m of messages) {
      if (m.role === "cowork") ajouter(JSON.parse(m.details));
      else fil.append(bulle(m));
    }
    afficherVue("discussion");
    defilerEnBas();
    chargerConversations();
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
    if (/n'est pas proposé/.test(e.message)) chargerModes();
  } finally {
    clearInterval(minuteur);
    etat.occupe = false;
    $("form-saisie").classList.remove("occupe");
    defilerEnBas();
    chargerConversations();
  }
}

// ---------- Cowork ----------

function carteEtape(nomIcone, titre, detail, classe) {
  const carte = element("div", classe);
  const ligne = element("div", "etape-ligne");
  ligne.append(icone(nomIcone), element("span", "etape-titre", titre));
  if (detail) ligne.append(element("span", "etape-detail", detail));
  carte.append(ligne);
  return carte;
}

function ajouterResultat(carte, ev) {
  const statut = element("span", `etape-statut ${ev.ok ? "ok" : "ko"}`);
  statut.append(icone(ev.ok ? "i-check" : "i-alerte"));
  carte.querySelector(".etape-ligne").append(statut);
  if (ev.diff) {
    const diff = element("div", "diff");
    for (const ligne of ev.diff.split("\n")) diff.append(element("div", ligne.startsWith("-") ? "moins" : "plus", ligne));
    carte.append(diff);
  } else if (!ev.ok || ["commande", "lire", "chercher", "lister"].includes(carte.dataset.action)) {
    const details = element("details");
    details.open = !ev.ok;
    details.append(element("summary", null, ev.ok ? "Voir le résultat" : "Erreur"), element("pre", null, ev.corps));
    carte.append(details);
  }
}

function carteDemande(ev, detail, interactif) {
  const carte = carteEtape("i-alerte", libelleEtape(ev).titre, "", "etape demande");
  if (detail) carte.append(element("code", "demande-code", detail));
  carte.append(element("div", "demande-raison", `Pourquoi : ${ev.raison}.`));
  if (!interactif) {
    carte.append(element("div", "demande-decision", "Décision déjà prise."));
    return carte;
  }
  const actions = element("div", "demande-actions");
  const toujours = element("label");
  const caseToujours = element("input");
  caseToujours.type = "checkbox";
  toujours.append(caseToujours, document.createTextNode("Toujours autoriser ce type ici"));
  const refuser = element("button", "bouton-refuser", "Refuser");
  refuser.type = "button";
  const continuer = element("button", "bouton-continuer", "Continuer");
  continuer.type = "button";
  const decider = async (reponse) => {
    actions.replaceWith(
      element("div", "demande-decision", reponse === "continuer" ? "Tu as autorisé cette action." : "Tu as refusé cette action."),
    );
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

// Affiche les étapes d'une tâche dans `conteneur` ; `interactif` = boutons d'accord actifs.
function creerRenduCowork(conteneur, interactif) {
  let derniereAction = null; // carte « action » qui recevra son résultat
  return (ev) => {
    const { icone: nomIcone, titre, detail } = libelleEtape(ev);
    if (ev.type === "action") {
      derniereAction = carteEtape(nomIcone, titre, detail, "etape");
      derniereAction.dataset.action = ev.action;
      derniereAction.dataset.detail = detail;
      conteneur.append(derniereAction);
    } else if (ev.type === "resultat") {
      if (derniereAction) ajouterResultat(derniereAction, ev);
    } else if (ev.type === "demande") {
      conteneur.append(carteDemande(ev, derniereAction?.dataset.detail ?? "", interactif));
    } else if (ev.type === "termine") {
      conteneur.append(bulle({ role: "gemini", texte: ev.resume.replace(/^TERMINÉ\s*:\s*/, ""), modele: null, niveau: null, duree: null }));
    } else {
      conteneur.append(carteEtape(nomIcone, titre, detail, ev.type === "erreur" ? "etape info erreur-etape" : "etape info"));
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
    chargerConversations(); // la conversation apparaît tout de suite dans la barre latérale
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

function ecouterFlux(identifiant) {
  const ajouter = creerRenduCowork($("fil"), true);
  etat.tache = identifiant;
  $("arreter").hidden = false;
  const source = new EventSource(`/api/cowork/${identifiant}/flux`);
  source.onmessage = (message) => {
    const ev = JSON.parse(message.data);
    if (etat.courante === identifiant) ajouter(ev); // seulement si la conversation est encore affichée
    if (FIN_DE_TACHE.includes(ev.type)) {
      source.close();
      finirCowork();
      if (ev.type === "termine") signaler("Gemini prêt", VERT);
      else signaler(libelleEtape(ev).titre, ROUGE);
    } else if (ev.type === "demande") {
      signaler("En attente de ta décision", ORANGE);
    } else {
      signaler(`Cowork travaille… étape ${ev.etape + 1}`, ORANGE);
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
  $("form-saisie").classList.remove("occupe");
  $("arreter").hidden = true;
  chargerConversations();
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

function dessinerMode() {
  $("modes").querySelectorAll("button").forEach((b) => b.classList.toggle("actif", b.dataset.mode === etat.mode));
  $("ligne-dossier").hidden = etat.mode !== "cowork";
  $("nom-dossier").textContent = etat.dossier ?? "Choisir un dossier de travail";
  $("choisir-dossier").title = etat.dossier ?? "Choisir le dossier de travail";
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
    ["Conversations", "Sur la période", "i-messages", String(s.conversations)],
    ["Messages", "Envoyés à Gemini", "i-graphique", String(s.messages)],
    // Un nom de modèle est plus long qu'un nombre : écrit plus petit pour tenir dans la carte.
    ["Modèle favori", "Le plus utilisé", "i-etincelle", s.modele_favori ?? "—", "texte"],
    ["Temps moyen", "Par réponse", "i-horloge", s.temps_moyen == null ? "—" : formaterDuree(s.temps_moyen)],
  ];
  $("cartes").replaceChildren(
    ...cartes.map(([titre, sousTitre, nomIcone, valeur, style = ""]) => {
      const carte = element("div", "carte");
      const boite = element("div", "carte-valeur");
      const rond = element("span", "rond");
      rond.append(icone(nomIcone));
      boite.append(rond, element("span", `nombre ${style}`, valeur));
      carte.append(element("div", "carte-titre", titre), element("div", "carte-sous", sousTitre), boite);
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
      ligne.append(ouvrir, infos, supprimer);
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
  $("parametres").showModal();
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
  $("replier").addEventListener("click", basculerBarre);
  $("deplier").addEventListener("click", basculerBarre);
  $("bouton-modele").addEventListener("click", basculerMenu);
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
    if (!e.target.closest(".menu-modele")) fermerMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") fermerMenu();
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
  await chargerModes();
  const defaut = lire(CLE_DEFAUT, {});
  choisirReglages(defaut.modele, defaut.niveau);
  setInterval(() => {
    if (!etat.occupe) verifierEtat();
  }, 30000);
}

demarrer();
