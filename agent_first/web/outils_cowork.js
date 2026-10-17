// Libellés et calculs des étapes Cowork (fonctions pures, testées avec `node --test tests/web/`).

// Actions du catalogue d'Agent First (cowork/catalogue.py). verbe : mot court en monospace, comme dans un terminal.
const ACTIONS = {
  list: { icone: "i-dossier", verbe: "List", titre: "Dossier listé", champ: "path" },
  read: { icone: "i-fichier", verbe: "Read", titre: "Fichier lu", champ: "path" },
  search: { icone: "i-recherche", verbe: "Search", titre: "Recherche", champ: "pattern" },
  create: { icone: "i-fichier", verbe: "Write", titre: "Fichier créé", champ: "path" },
  edit: { icone: "i-crayon", verbe: "Edit", titre: "Fichier modifié", champ: "path" },
  delete: { icone: "i-corbeille", verbe: "Delete", titre: "Suppression", champ: "path" },
  run: { icone: "i-terminal", verbe: "Run", titre: "Commande", champ: "command" },
  start: { icone: "i-terminal", verbe: "Start", titre: "Processus lancé", champ: "command" },
  logs: { icone: "i-terminal", verbe: "Logs", titre: "Sortie d'un processus", champ: "id" },
  stop: { icone: "i-stop", verbe: "Stop", titre: "Processus arrêté", champ: "id" },
  visit: { icone: "i-fleche", verbe: "Visit", titre: "Page visitée", champ: "url" },
};

// Les conversations d'avant la v3 ont des actions aux noms français.
const ANCIENS = {
  lister: "list",
  lire: "read",
  chercher: "search",
  creer: "create",
  modifier: "edit",
  supprimer: "delete",
  commande: "run",
};
const CHAMPS_ANCIENS = { chemin: "path", contenu: "content", avant: "old", apres: "new", texte: "command", motif: "pattern" };

const AUTRES = {
  plan: { icone: "i-check", titre: "Plan" },
  tour: { icone: "i-horloge", titre: "Réponse de Gemini" },
  saute: { icone: "i-fermer", titre: "Action sautée : une action précédente a échoué" },
  demande: { icone: "i-alerte", titre: "Action jugée dangereuse : ton accord est nécessaire" },
  autorise: { icone: "i-check", titre: "Action dangereuse autorisée d'office (toujours autoriser)" },
  refus: { icone: "i-fermer", titre: "Action refusée" },
  erreur_format: { icone: "i-alerte", titre: "Gemini n'a pas respecté le format, rappel envoyé" },
  erreur_gemini: { icone: "i-alerte", titre: "Gemini a eu un problème, message renvoyé" },
  relance_fin: { icone: "i-alerte", titre: "Fin refusée, Gemini continue" },
  question: { icone: "i-messages", titre: "Gemini te pose une question" },
  termine: { icone: "i-check", titre: "Terminé" },
  limite: { icone: "i-alerte", titre: "Limite d'allers-retours atteinte" },
  arret: { icone: "i-fermer", titre: "Tâche arrêtée" },
  erreur: { icone: "i-alerte", titre: "Erreur" },
};

export function normaliserAction(ev) {
  const action = ANCIENS[ev.action] ?? ev.action;
  const champs = {};
  for (const [cle, valeur] of Object.entries(ev.champs ?? {})) champs[CHAMPS_ANCIENS[cle] ?? cle] = valeur;
  return { action, champs };
}

export function libelleEtape(ev) {
  if (ev.type === "action" || ev.type === "saute") {
    const { action, champs } = normaliserAction(ev);
    const a = ACTIONS[action] ?? { icone: "i-etincelle", verbe: action, titre: action, champ: null };
    let detail = a.champ ? String(champs[a.champ] ?? "") : "";
    if (a.champ === "id" && detail) detail = `#${detail.replace(/^#/, "")}`;
    const titre = ev.type === "saute" ? AUTRES.saute.titre : a.titre;
    return { icone: a.icone, verbe: a.verbe, titre, detail };
  }
  const autre = AUTRES[ev.type] ?? { icone: "i-etincelle", titre: ev.type };
  return { icone: autre.icone, verbe: ev.type, titre: autre.titre, detail: ev.raison ?? ev.resume ?? ev.question ?? ev.corps ?? "" };
}

// Une réponse de Gemini, avec son temps : on voit où part le temps d'une tâche.
export function detailTour(ev) {
  return `Gemini a répondu en ${secondes(ev.gemini)}`;
}

function secondes(valeur) {
  return `${Math.round(valeur ?? 0)} s`;
}

export function estDangereuse(ev) {
  return ev.type === "demande";
}

// Diff unifié : on compte les lignes ajoutées et retirées, pas le contexte ni les en-têtes.
export function resumeDiff(diff) {
  const lignes = diff ? diff.split("\n") : [];
  return {
    plus: lignes.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length,
    moins: lignes.filter((l) => l.startsWith("-") && !l.startsWith("---")).length,
  };
}

export function nombreLignes(texte) {
  if (!texte) return "fichier vide";
  const n = texte.replace(/\n$/, "").split("\n").length;
  return `${n} ligne${n > 1 ? "s" : ""}`;
}

export function avancementPlan(etapes) {
  return { faites: etapes.filter((e) => e.fait).length, total: etapes.length };
}

function pluriel(n, mot) {
  return `${n} ${mot}${n > 1 ? "s" : ""}`;
}

// Le bilan factuel d'Agent First : ce qui a vraiment changé, et ce qui a été vérifié.
export function lignesBilan(bilan) {
  const echecs = (bilan.commandes ?? []).filter((c) => c.code !== null && c.code !== undefined && c.code !== 0).length;
  const verifications = bilan.verifications ?? 0;
  const morceaux = [
    pluriel(bilan.crees?.length ?? 0, "créé"),
    pluriel(bilan.modifies?.length ?? 0, "modifié"),
    pluriel(bilan.supprimes?.length ?? 0, "supprimé"),
    verifications ? pluriel(verifications, "vérification") : "aucune vérification",
  ];
  if (echecs) morceaux.push(`${echecs} en échec`);
  if (bilan.temps) morceaux.push(`Gemini ${secondes(bilan.temps.gemini)} · actions ${secondes(bilan.temps.actions)}`);
  const fichiers = [
    ...(bilan.crees ?? []).map((chemin) => ({ signe: "+", chemin })),
    ...(bilan.modifies ?? []).map((chemin) => ({ signe: "~", chemin })),
    ...(bilan.supprimes ?? []).map((chemin) => ({ signe: "−", chemin })),
  ];
  return { compteurs: morceaux.join(" · "), fichiers };
}

// Petite info à droite d'une ligne d'étape, tirée du résultat.
export function infoResultat(action, corps) {
  const texte = corps ?? "";
  if (action === "visit") return texte.match(/^HTTP (\d+)/)?.[1] ?? "";
  if (action === "start") return texte.match(/^started (#\d+)/)?.[1] ?? "";
  if (action === "read") return nombreLignes(texte);
  if (action === "list") {
    const n = texte.startsWith("(") ? 0 : texte.split("\n").filter(Boolean).length;
    return pluriel(n, "entrée");
  }
  return "";
}
