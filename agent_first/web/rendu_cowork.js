// Les étapes d'une tâche Cowork dans le fil : une ligne monospace par action, plan, bilan,
// question et demandes d'accord.
import { appeler } from "./api.js";
import { $, element, icone, notifier } from "./dom.js";
import { etat, nom } from "./etat.js";
import { bulle, defilerEnBas, estEnBas } from "./fil.js";
import { avancementPlan, detailTour, infoResultat, libelleEtape, lignesBilan, nombreLignes, normaliserAction, resumeDiff } from "./outils_cowork.js";

export const FIN_DE_TACHE = ["termine", "limite", "arret", "erreur", "question"];

// Une étape = une ligne : point d'état, verbe (Write, Edit, Run…), détail, info, et un contenu
// qu'on peut déplier (diff, sortie de commande, fichier écrit).
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

// Évènement sans action (refus, autorisation d'office, limite, arrêt, secours…) : une ligne discrète.
function noteEtape(ev, etatPoint) {
  const { titre, detail } = libelleEtape(ev);
  const note = element("div", ev.type === "secours" ? "etape-note secours" : "etape-note");
  note.append(element("span", `point-etat ${etatPoint}`), element("span", null, ev.type === "secours" ? "Secours" : titre));
  const texte = ev.type === "secours" ? ev.corps : detail;
  if (texte) {
    note.append(element("span", "etape-detail", texte));
    note.title = texte;
  }
  return note;
}

// Réponse hors format : repliée, avec ce que le modèle a écrit (pour comprendre ce qui s'est passé).
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
    try {
      await appeler("POST", `/api/cowork/${etat.tache}/decision`, { etape: ev.etape, reponse, toujours: caseToujours.checked });
    } catch (e) {
      notifier(e.message, "erreur");
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

// Ce qu'Agent First a constaté, indépendamment de ce que le modèle annonce.
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
  titre.append(icone("i-messages"), element("span", null, "Question pour toi"));
  carte.append(titre, element("div", "question-texte", ev.question));
  if (interactif) carte.append(element("div", "question-aide", "Réponds dans la zone de saisie : la tâche reprendra là où elle s'est arrêtée."));
  return carte;
}

// Affiche les étapes d'une tâche dans `conteneur` ; `interactif` = tâche en direct (boutons d'accord
// actifs). `dessinerProcessus(liste)` met à jour les processus de l'en-tête.
export function creerRenduCowork(conteneur, interactif, dessinerProcessus) {
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
    const suivre = estEnBas(); // avant d'ajouter : le fil ne suit que si on était déjà en bas
    // La tâche avance : une demande restée ouverte a été tranchée ailleurs (API, autre fenêtre).
    if (accordOuvert?.isConnected) accordOuvert.replaceWith(element("div", "accord-decision", "Décision prise."));
    accordOuvert = null;
    if (ev.type === "tour") {
      ajouterLigne(element("div", "etape-tour", detailTour(ev, nom(etat.conversation?.fournisseur ?? "gemini"))));
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
      conteneur.append(bulle({ role: "reponse", texte: ev.resume.replace(/^TERMINÉ\s*:\s*/, ""), fournisseur: etat.conversation?.fournisseur, modele: null, niveau: null, duree: null }));
      ajouterBilan(ev.bilan);
    } else {
      if (ev.type === "refus" && derniere) marquerEtape(derniere, "ko");
      const point = ["autorise", "erreur_gemini", "relance_fin", "secours"].includes(ev.type) ? "decision" : ev.type === "relais" ? "" : "ko";
      ajouterLigne(noteEtape(ev, point));
      if (FIN_DE_TACHE.includes(ev.type)) ajouterBilan(ev.bilan);
    }
    defilerEnBas(suivre);
  };
}
