// agent.first — l'app : barre latérale, discussion (Chat et Cowork), tableau de bord.
import { appeler, appelerFlux } from "./api.js";
import { $, boutonIcone, ecrire, element, icone, lire, notifier } from "./dom.js";
import { etat, fournisseur, nom } from "./etat.js";
import { brancherDefilement, bulle, bulleAttente, bulleEnEcriture, defilerEnBas, estEnBas } from "./fil.js";
import { brancherMenus, dessinerMenus, fermerMenus, menusOuverts } from "./menus.js";
import { cheminCourt, choixValide, formaterDate, formaterDuree, groupesParDate, libelleEtat, titreDepuis } from "./outils.js";
import { libelleEtape } from "./outils_cowork.js";
import { brancherPalette, ouvrirPalette } from "./palette.js";
import { brancherParametres, choixParDefaut, ouvrirParametres } from "./parametres.js";
import { creerRenduCowork, FIN_DE_TACHE } from "./rendu_cowork.js";

const CLE_BARRE = "agent.first.barre-repliee";
const CLE_DOSSIER = "agent.first.dossier";
const AIDE = "Entrée pour envoyer · Maj+Entrée pour aller à la ligne";

// ---------- statut (sous la zone de saisie) ----------

function statut(texte, genre = "") {
  const pied = $("pied");
  if (!texte) {
    pied.replaceChildren(element("span", "pied-aide", AIDE));
    return;
  }
  pied.replaceChildren(element("span", `point ${genre}`), element("span", "statut", texte));
}

function occuper(occupe, reponse = false) {
  etat.occupe = occupe;
  etat.reponseEnCours = occupe && reponse;
  $("envoyer").hidden = occupe;
  $("arreter").hidden = !occupe;
  if (!occupe) statut(null);
}

function afficherVue(vue) {
  $("vue-accueil").hidden = vue !== "accueil";
  $("vue-discussion").hidden = vue !== "discussion";
  $("aller-accueil").classList.toggle("actif", vue === "accueil");
}

function ajusterSaisie() {
  const saisie = $("saisie");
  saisie.style.height = "auto";
  saisie.style.height = `${Math.min(saisie.scrollHeight, 240)}px`;
}

// ---------- fournisseurs et état ----------

async function chargerFournisseurs() {
  try {
    const r = await appeler("GET", "/api/fournisseurs");
    etat.fournisseurs = r.actifs;
    etat.tous = r.tous;
    etat.secours = r.secours;
  } catch {
    // Agent First injoignable : la barre le dit (verifierEtat)
  }
  etat.choix = choixValide(etat.fournisseurs, etat.choix);
  dessinerMenus();
  dessinerEtatsFournisseurs();
}

function dessinerEtatsFournisseurs() {
  const zone = $("etats-fournisseurs");
  if (!etat.serveur) {
    const ligne = element("div", "etat-fournisseur");
    ligne.append(element("span", "point panne"), element("span", "nom", "Agent First arrêté"));
    zone.replaceChildren(ligne);
    return;
  }
  zone.replaceChildren(...etat.fournisseurs.map((f) => {
    const ligne = element("button", "etat-fournisseur");
    ligne.type = "button";
    const detail = libelleEtat(f.etat, f.detail);
    ligne.title = `${f.nom}${detail ? ` : ${detail}` : f.etat === "pret" ? " : prêt" : ""}`;
    ligne.append(element("span", `point ${f.etat}`), element("span", "nom", f.nom));
    // Le point dit déjà « limite » : ici, seulement jusqu'à quand.
    const court = f.etat === "limite" && f.detail ? f.detail : detail;
    if (court) ligne.append(element("span", `detail ${f.etat}`, court));
    ligne.addEventListener("click", () => ouvrirParametres("fournisseurs", f.id));
    return ligne;
  }));
}

async function verifierEtat() {
  try {
    etat.serveur = await appeler("GET", "/api/etat");
    for (const f of etat.fournisseurs) Object.assign(f, etat.serveur.fournisseurs?.[f.id] ?? {});
    if (etat.serveur.google === false) {
      const gemini = fournisseur("gemini");
      if (gemini) Object.assign(gemini, { etat: "deconnecte", detail: null });
    }
  } catch {
    etat.serveur = null;
  }
  dessinerEtatsFournisseurs();
  dessinerMenus();
}

// ---------- barre latérale ----------

async function chargerConversations() {
  const liste = $("liste-conversations");
  let conversations;
  try {
    conversations = await appeler("GET", "/api/conversations");
  } catch {
    liste.replaceChildren(element("p", "vide", "Historique indisponible."));
    return;
  }
  if (!conversations.length) {
    liste.replaceChildren(element("p", "vide", "Tes conversations apparaîtront ici."));
    return;
  }
  const contenu = [];
  for (const groupe of groupesParDate(conversations)) {
    contenu.push(element("div", "groupe-titre", groupe.titre));
    for (const c of groupe.conversations) contenu.push(ligneConversation(c));
  }
  liste.replaceChildren(...contenu);
}

function ligneConversation(c) {
  const ligne = element("div", "conversation");
  ligne.tabIndex = 0;
  ligne.setAttribute("role", "button");
  ligne.title = [c.mode === "cowork" ? "Cowork" : null, nom(c.fournisseur), c.source === "api" ? "API" : null, c.titre].filter(Boolean).join(" · ");
  ligne.classList.toggle("actif", c.id === etat.courante);
  // marque : point ambre si une tâche attend un accord, point qui pulse si elle tourne,
  // sinon terminal pour Cowork, rien pour Chat
  const marque = element("span", "marque");
  if (etat.attentes.has(c.id)) marque.classList.add("attente");
  else if (c.id === etat.tache || etat.actives.has(c.id)) marque.classList.add("en-cours");
  else if (c.mode === "cowork") marque.append(icone("i-terminal"));
  const titre = element("span", "conversation-titre", c.titre || "Sans titre");
  const actions = element("span", "conversation-actions");
  actions.append(
    boutonIcone("i-crayon", "Renommer", () => renommer(c, titre)),
    boutonIcone("i-corbeille", "Retirer de l'historique", () => supprimerConversation(c)),
  );
  ligne.append(marque, titre, actions);
  ligne.addEventListener("click", () => ouvrirConversation(c.id));
  ligne.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target === ligne) ouvrirConversation(c.id);
  });
  return ligne;
}

// Titre modifié sur place : Entrée garde, Échap annule.
function editerTitre(porteur, actuel, enregistrer) {
  const champ = element("input");
  champ.value = actuel;
  porteur.replaceChildren(champ);
  champ.focus();
  champ.select();
  let fini = false;
  const finir = async (garder) => {
    if (fini) return;
    fini = true;
    const nouveau = champ.value.trim();
    porteur.textContent = garder && nouveau ? nouveau : actuel;
    if (garder && nouveau && nouveau !== actuel) await enregistrer(nouveau);
  };
  champ.addEventListener("click", (e) => e.stopPropagation());
  champ.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") finir(true);
    if (e.key === "Escape") finir(false);
  });
  champ.addEventListener("blur", () => finir(true));
}

function renommer(c, porteur) {
  editerTitre(porteur, c.titre || "Sans titre", async (titre) => {
    try {
      await appeler("PATCH", `/api/conversations/${c.id}`, { titre });
      if (etat.courante === c.id) $("titre-conversation").textContent = titre;
      chargerConversations();
    } catch (e) {
      notifier(e.message, "erreur");
    }
  });
}

async function supprimerConversation(c) {
  if (!confirm(`Retirer « ${c.titre || "Sans titre"} » de l'historique de l'app ?\nElle reste chez le fournisseur (Gemini…).`)) return;
  try {
    await appeler("DELETE", `/api/conversations/${c.id}`);
    if (etat.courante === c.id) nouvelleConversation();
    notifier("Conversation retirée", "ok");
    chargerConversations();
    if (!$("vue-accueil").hidden) chargerAccueil();
  } catch (e) {
    notifier(e.message, "erreur");
  }
}

function basculerBarre() {
  ecrire(CLE_BARRE, document.body.classList.toggle("barre-repliee"));
}

// ---------- discussion ----------

function accueilDiscussion() {
  const bloc = element("div", "vide-discussion");
  const f = fournisseur(etat.choix.fournisseur);
  const pilule = element("div", "vide-fournisseur");
  pilule.append(element("span", `point ${f?.etat ?? ""}`), element("span", null, f ? `${f.nom}${etat.choix.modele && etat.choix.modele !== "Par défaut" ? ` · ${etat.choix.modele}` : ""}` : "Aucun fournisseur"));
  if (etat.mode === "cowork") {
    bloc.append(element("h1", null, "Travaille sur ton PC"));
    const aide = element("p");
    if (etat.dossier) {
      aide.append(
        "L'IA fait un plan, lit, crée et modifie des fichiers, lance des commandes et des serveurs dans ",
        element("code", null, cheminCourt(etat.dossier)),
        ", puis vérifie son travail. Les actions risquées attendent ton accord.",
      );
      bloc.append(aide, pilule);
    } else {
      aide.textContent = "Choisis d'abord le dossier de travail, puis décris la tâche.";
      const choisir = element("button", "bouton-secondaire", "Choisir un dossier");
      choisir.type = "button";
      choisir.prepend(icone("i-dossier"));
      choisir.addEventListener("click", choisirDossier);
      bloc.append(aide, choisir);
    }
    return bloc;
  }
  bloc.append(element("h1", null, "Nouvelle conversation"), element("p", null, "Choisis le fournisseur et le modèle sous la zone de saisie, puis pose ta question."), pilule);
  return bloc;
}

function nouvelleConversation() {
  etat.courante = null;
  etat.conversation = null;
  if (etat.mode === "cowork") etat.dossier = lire(CLE_DOSSIER, null);
  $("titre-conversation").textContent = "Nouvelle conversation";
  etat.choix = choixParDefaut();
  dessinerMenus();
  dessinerMode();
  dessinerProcessus([]);
  $("fil").replaceChildren(accueilDiscussion());
  defilerEnBas(true);
  afficherVue("discussion");
  chargerConversations();
  $("saisie").focus();
}

async function ouvrirConversation(identifiant) {
  try {
    const { conversation, messages, tache } = await appeler("GET", `/api/conversations/${identifiant}`);
    if (etat.flux && etat.tache !== conversation.id) {
      etat.flux.close(); // la tâche suivie continue sur Agent First ; on la retrouvera en revenant
      etat.flux = null;
      etat.tache = null;
    }
    etat.courante = conversation.id;
    etat.conversation = conversation;
    etat.mode = conversation.mode ?? "chat";
    etat.dossier = conversation.dossier ?? null;
    $("titre-conversation").textContent = conversation.titre || "Conversation";
    etat.choix = choixValide(etat.fournisseurs, { fournisseur: conversation.fournisseur, modele: conversation.modele, niveau: conversation.niveau });
    dessinerMenus();
    dessinerMode();
    const fil = $("fil");
    fil.replaceChildren();
    const ajouter = creerRenduCowork(fil, false, dessinerProcessus);
    // Tâche en cours : ses étapes viendront du flux (rejouées, accord compris) ; ici, seulement ce qui précède.
    const fin = tache?.en_cours ? messages.map((m) => m.role).lastIndexOf("toi") + 1 : messages.length;
    for (const m of messages.slice(0, fin)) {
      if (m.role === "cowork") ajouter(JSON.parse(m.details));
      else fil.append(bulle(m));
    }
    afficherVue("discussion");
    defilerEnBas(true);
    dessinerProcessus([]);
    if (etat.mode === "cowork") chargerProcessus(conversation.id);
    if (tache?.en_cours) ecouterFlux(conversation.id, 0);
    else {
      occuper(false);
      chargerConversations();
    }
    dessinerBandeau();
    $("saisie").focus();
  } catch (e) {
    notifier(e.message, "erreur");
  }
}

function envoyer() {
  const texte = $("saisie").value.trim();
  if (!texte || etat.occupe) return;
  if (!etat.choix.fournisseur) {
    notifier("Aucun fournisseur actif : ouvre Paramètres → Fournisseurs", "attention");
    return;
  }
  if (etat.mode === "cowork") return envoyerCowork(texte);
  return envoyerChat(texte);
}

async function creerConversation(extra = {}) {
  const { fournisseur: f, modele, niveau } = etat.choix;
  const conversation = await appeler("POST", "/api/conversations", { fournisseur: f, modele, niveau, ...extra });
  etat.courante = conversation.id;
  etat.conversation = conversation;
}

async function envoyerChat(texte) {
  occuper(true, true);
  $("saisie").value = "";
  ajusterSaisie();
  const fil = $("fil");
  fil.querySelector(".vide-discussion")?.remove();
  fil.append(bulle({ role: "toi", texte }));
  const nomF = nom(etat.choix.fournisseur);
  const { attente, libelle } = bulleAttente(`${nomF} réfléchit…`);
  fil.append(attente);
  defilerEnBas(true);
  if (!etat.courante) $("titre-conversation").textContent = titreDepuis(texte);

  const debut = Date.now();
  let ecrit = false; // le premier morceau de réponse est arrivé
  const tic = () => {
    const ecoule = `${nomF} ${ecrit ? "écrit" : "réfléchit"}… ${formaterDuree((Date.now() - debut) / 1000)}`;
    libelle.textContent = ecoule;
    statut(ecoule, "en-cours");
  };
  tic();
  const minuteur = setInterval(tic, 1000);
  const enCours = bulleEnEcriture();

  try {
    if (!etat.courante) await creerConversation();
    let fin = null;
    const { fournisseur: f, modele, niveau } = etat.choix;
    await appelerFlux(`/api/conversations/${etat.courante}/messages?flux=1`, { texte, fournisseur: f, modele, niveau }, (ev) => {
      if (ev.type === "partiel") {
        const suivre = estEnBas(); // avant d'ajouter du texte : après, on ne serait plus « en bas »
        if (!ecrit) attente.replaceWith(enCours.carte);
        ecrit = true;
        enCours.afficher(ev.texte, ev.html);
        defilerEnBas(suivre);
      } else fin = ev;
    });
    if (!fin) throw new Error("Réponse incomplète : Agent First s'est peut-être arrêté.");
    if (fin.type === "erreur") throw new Error(fin.erreur);
    (ecrit ? enCours.carte : attente).replaceWith(bulle(fin.message));
    if (fin.message.fournisseur && fin.message.fournisseur !== etat.choix.fournisseur) {
      notifier(`Réponse du secours : ${nom(fin.message.fournisseur)}`, "attention", 5000);
    }
    const conv = await appeler("GET", `/api/conversations/${etat.courante}`).catch(() => null);
    if (conv) {
      etat.conversation = conv.conversation; // après un secours, la conversation continue chez lui
      etat.choix = choixValide(etat.fournisseurs, { fournisseur: conv.conversation.fournisseur, modele: conv.conversation.modele, niveau: conv.conversation.niveau ?? etat.choix.niveau });
    }
  } catch (e) {
    (ecrit ? enCours.carte : attente).replaceWith(bulle({ role: "erreur", texte: e.message }, () => {
      $("saisie").value = texte;
      envoyer();
    }));
    $("saisie").value = texte; // pour pouvoir le renvoyer
    ajusterSaisie();
  } finally {
    clearInterval(minuteur);
    occuper(false);
    defilerEnBas();
    chargerConversations();
    await chargerFournisseurs(); // états à jour (limite, secours…)
  }
}

// ---------- Cowork ----------

async function envoyerCowork(texte) {
  if (!etat.dossier) {
    notifier("Choisis d'abord un dossier de travail", "attention");
    return;
  }
  occuper(true);
  $("saisie").value = "";
  ajusterSaisie();
  const fil = $("fil");
  fil.querySelector(".vide-discussion")?.remove();
  fil.append(bulle({ role: "toi", texte }));
  if (!etat.courante) $("titre-conversation").textContent = titreDepuis(texte);
  defilerEnBas(true);
  statut("Cowork démarre…", "en-cours");
  try {
    if (!etat.courante) await creerConversation({ mode: "cowork", dossier: etat.dossier });
    const { fournisseur: f, modele, niveau } = etat.choix;
    await appeler("POST", `/api/cowork/${etat.courante}/messages`, { texte, fournisseur: f, modele, niveau });
    etat.conversation = { ...(etat.conversation ?? {}), fournisseur: f };
  } catch (e) {
    fil.append(bulle({ role: "erreur", texte: e.message }));
    $("saisie").value = texte; // pour pouvoir le renvoyer
    ajusterSaisie();
    finirCowork();
    return;
  }
  ecouterFlux(etat.courante);
}

// Suit une tâche en direct. Rouvrir une conversation dont la tâche tourne rejoue ses étapes (depuis 0).
// Une coupure (veille, réseau) : on se reconnecte là où on s'était arrêté, tant que la tâche tourne.
function ecouterFlux(identifiant, depuis = 0) {
  etat.flux?.close();
  const ajouter = creerRenduCowork($("fil"), true, dessinerProcessus);
  etat.tache = identifiant;
  occuper(true);
  chargerConversations(); // la conversation apparaît tout de suite, avec son point « en cours »
  let actions = 0;
  let position = depuis;
  let essais = 0;

  const brancher = () => {
    const source = new EventSource(`/api/cowork/${identifiant}/flux?depuis=${position}`);
    etat.flux = source;
    source.onmessage = (message) => {
      essais = 0;
      position += 1;
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
        if (ev.type === "termine") notifier("Tâche terminée", "ok");
        else if (ev.type === "question") {
          notifier("Une question t'attend", "attention");
          if (etat.courante === identifiant) $("saisie").focus();
        } else notifier(libelleEtape(ev).titre, "erreur");
      } else if (ev.type === "statut") {
        if (ev.statut === "waiting_approval") statut("En attente de ta décision", "limite");
        if (ev.statut === "queued") statut("En file d'attente : une autre tâche se termine…", "limite");
      } else if (ev.type !== "processus" && ev.type !== "demande") {
        statut(`Cowork travaille… ${actions} action${actions > 1 ? "s" : ""}`, "en-cours");
      }
    };
    source.onerror = async () => {
      source.close();
      if (etat.tache !== identifiant) return;
      // La tâche tourne-t-elle encore ? Sinon on relit la conversation (le bilan est enregistré).
      const lue = await appeler("GET", `/api/conversations/${identifiant}`).catch(() => null);
      if (etat.tache !== identifiant) return;
      if (lue?.tache?.en_cours && essais < 8) {
        essais += 1;
        statut("Connexion perdue : reprise…", "limite");
        setTimeout(() => etat.tache === identifiant && brancher(), Math.min(10000, 1000 * 2 ** (essais - 1)));
        return;
      }
      finirCowork();
      if (lue) {
        if (etat.courante === identifiant) ouvrirConversation(identifiant);
      } else notifier("Agent First injoignable : la tâche n'est plus suivie", "erreur");
    };
  };
  brancher();
}

function finirCowork() {
  etat.flux?.close();
  etat.tache = null;
  etat.flux = null;
  occuper(false);
  chargerConversations();
  chargerFournisseurs();
  if (etat.mode === "cowork" && etat.courante) chargerProcessus(etat.courante); // les serveurs lancés restent affichés
}

async function arreter() {
  if (!etat.occupe || !etat.courante) return;
  try {
    if (etat.reponseEnCours) {
      await appeler("POST", `/api/conversations/${etat.courante}/arreter`);
      statut("Arrêt demandé…", "limite");
    } else if (etat.tache) {
      await appeler("POST", `/api/cowork/${etat.tache}/arreter`);
      statut("Arrêt demandé (après l'étape en cours)…", "limite");
    }
  } catch (e) {
    notifier(e.message, "erreur");
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
      const bouton = element("button", "pilule-arreter", "Arrêter");
      bouton.type = "button";
      bouton.addEventListener("click", () => arreterProcessus(p.id));
      pilule.append(element("span", "point-processus"), element("span", "pilule-commande", `#${p.id} ${p.commande}`), bouton);
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
    notifier(r.ok ? `Processus #${numero} arrêté` : r.corps, r.ok ? "ok" : "erreur");
  } catch (e) {
    notifier(e.message, "erreur");
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
  $("saisie").placeholder = etat.mode === "cowork" ? "Décris une tâche à faire sur ton PC…" : "Écris ton message…";
}

function choisirMode(mode) {
  if (etat.occupe) {
    notifier("Attends la fin de la réponse ou de la tâche en cours", "attention");
    return;
  }
  if (mode === etat.mode && !etat.courante) return;
  etat.mode = mode;
  nouvelleConversation();
}

async function choisirDossier() {
  if (etat.occupe) return;
  try {
    notifier("Choisis le dossier dans la fenêtre Windows…");
    const { dossier } = await appeler("POST", "/api/dossiers/choisir");
    if (!dossier) return;
    ecrire(CLE_DOSSIER, dossier);
    if (etat.courante && dossier !== etat.dossier) {
      etat.dossier = dossier;
      nouvelleConversation(); // un autre dossier = une nouvelle conversation
    } else {
      etat.dossier = dossier;
      dessinerMode();
      $("fil").querySelector(".vide-discussion")?.replaceWith(accueilDiscussion());
    }
    notifier("Dossier de travail choisi", "ok");
  } catch (e) {
    notifier(e.message, "erreur");
  }
}

// ---------- tableau de bord / historique ----------

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
    notifier(e.message, "erreur");
  }
}

function dessinerCartes(s) {
  const cartes = [
    ["Conversations", "sur la période", String(s.conversations)],
    ["Messages", "envoyés", String(s.messages)],
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
    lignes.replaceChildren(element("p", "vide", recherche ? "Aucune conversation ne correspond." : "Aucune conversation sur cette période."));
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
      const infos = element("span", "ligne-infos", [c.modele && c.modele !== "Par défaut" ? c.modele : null, nombre, formaterDate(c.modifie_le)].filter(Boolean).join(" · "));
      const mode = [c.mode === "cowork" ? "cowork" : "chat", nom(c.fournisseur).toLowerCase(), c.source === "api" ? "api" : null].filter(Boolean).join(" · ");
      ligne.append(ouvrir, element("span", "ligne-mode", mode), infos,
        boutonIcone("i-corbeille", `Retirer « ${c.titre} » de l'historique`, () => supprimerConversation(c)));
      return ligne;
    }),
  );
}

// ---------- démarrage ----------

function brancherEvenements() {
  $("nouvelle").addEventListener("click", nouvelleConversation);
  $("ouvrir-palette").addEventListener("click", ouvrirPalette);
  $("aller-accueil").addEventListener("click", () => {
    afficherVue("accueil");
    chargerAccueil();
  });
  $("ouvrir-parametres").addEventListener("click", () => ouvrirParametres("general"));
  $("modes").addEventListener("click", (e) => {
    const bouton = e.target.closest("[data-mode]");
    if (bouton) choisirMode(bouton.dataset.mode);
  });
  $("choisir-dossier").addEventListener("click", choisirDossier);
  $("arreter").addEventListener("click", arreter);
  $("bandeau-ouvrir").addEventListener("click", () => {
    const id = $("bandeau-accord").dataset.conversation;
    if (id) ouvrirConversation(id);
  });
  $("replier").addEventListener("click", basculerBarre);
  $("deplier").addEventListener("click", basculerBarre);
  $("titre-conversation").addEventListener("dblclick", () => {
    if (!etat.courante) return;
    renommer({ id: etat.courante, titre: $("titre-conversation").textContent }, $("titre-conversation"));
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
  $("recherche-historique").addEventListener("input", () => {
    clearTimeout(attente);
    attente = setTimeout(chargerAccueil, 250);
  });
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
  document.addEventListener("keydown", (e) => {
    const touche = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && touche === "k") {
      e.preventDefault();
      ouvrirPalette();
    } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && touche === "o") {
      e.preventDefault();
      nouvelleConversation();
    } else if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
      if (menusOuverts()) fermerMenus();
      else if (etat.occupe) arreter();
    } else if (e.key === "/" && !e.target.closest("input, textarea, select, [contenteditable]")) {
      e.preventDefault();
      ouvrirPalette();
    }
  });
}

async function demarrer() {
  if (lire(CLE_BARRE, false)) document.body.classList.add("barre-repliee");
  brancherEvenements();
  brancherDefilement();
  brancherMenus({ ouvrirParametres, changement: () => $("fil").querySelector(".vide-discussion")?.replaceWith(accueilDiscussion()) });
  brancherParametres({
    rafraichir: chargerFournisseurs,
    changementDefaut: () => {
      if (!etat.courante) nouvelleConversation();
    },
  });
  brancherPalette({
    ouvrir: ouvrirConversation,
    actions: [
      { titre: "Nouvelle conversation", icone: "i-plus", raccourci: "Ctrl Maj O", faire: nouvelleConversation },
      { titre: "Nouvelle tâche Cowork", icone: "i-terminal", faire: () => choisirMode("cowork") },
      { titre: "Tableau de bord", icone: "i-accueil", faire: () => $("aller-accueil").click() },
      { titre: "Paramètres", icone: "i-reglages", faire: () => ouvrirParametres("general") },
      { titre: "Fournisseurs et clés API", icone: "i-reglages", faire: () => ouvrirParametres("fournisseurs") },
      { titre: "Secours si limite ou panne", icone: "i-relais", faire: () => ouvrirParametres("general") },
    ],
  });
  dessinerMode();
  afficherVue("accueil");
  await verifierEtat();
  await chargerFournisseurs();
  etat.choix = choixParDefaut();
  dessinerMenus();
  chargerConversations();
  chargerAccueil();
  ecouterEvenements();
  setInterval(() => {
    if (!etat.occupe) verifierEtat();
  }, 30000);
  setInterval(() => {
    if (!etat.occupe) chargerFournisseurs();
  }, 120000);
}

demarrer();
