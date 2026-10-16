// Libellés des étapes Cowork (fonctions pures, testées avec `node --test tests/web/`).

// verbe : mot court affiché en monospace sur la ligne de l'étape, comme dans un terminal.
const ACTIONS = {
  lister: { icone: "i-dossier", verbe: "List", titre: "Dossier listé", champ: "chemin" },
  lire: { icone: "i-fichier", verbe: "Read", titre: "Fichier lu", champ: "chemin" },
  chercher: { icone: "i-recherche", verbe: "Search", titre: "Recherche", champ: "motif" },
  creer: { icone: "i-fichier", verbe: "Write", titre: "Fichier créé", champ: "chemin" },
  modifier: { icone: "i-crayon", verbe: "Edit", titre: "Fichier modifié", champ: "chemin" },
  supprimer: { icone: "i-corbeille", verbe: "Delete", titre: "Suppression", champ: "chemin" },
  commande: { icone: "i-terminal", verbe: "Shell", titre: "Commande", champ: "texte" },
};

const AUTRES = {
  demande: { icone: "i-alerte", titre: "Action jugée dangereuse : ton accord est nécessaire" },
  autorise: { icone: "i-check", titre: "Action dangereuse autorisée d'office (toujours autoriser)" },
  refus: { icone: "i-fermer", titre: "Action refusée" },
  erreur_format: { icone: "i-alerte", titre: "Gemini n'a pas respecté le format, rappel envoyé" },
  termine: { icone: "i-check", titre: "Terminé" },
  limite: { icone: "i-alerte", titre: "Limite d'étapes atteinte" },
  arret: { icone: "i-fermer", titre: "Tâche arrêtée" },
  erreur: { icone: "i-alerte", titre: "Erreur" },
};

export function libelleEtape(ev) {
  if (ev.type === "action") {
    const a = ACTIONS[ev.action] ?? { icone: "i-etincelle", verbe: ev.action, titre: ev.action, champ: null };
    return { icone: a.icone, verbe: a.verbe, titre: a.titre, detail: a.champ ? (ev.champs?.[a.champ] ?? "") : "" };
  }
  const autre = AUTRES[ev.type] ?? { icone: "i-etincelle", titre: ev.type };
  return { icone: autre.icone, verbe: ev.type, titre: autre.titre, detail: ev.raison ?? ev.resume ?? ev.corps ?? "" };
}

export function estDangereuse(ev) {
  return ev.type === "demande";
}

export function resumeDiff(diff) {
  const lignes = diff ? diff.split("\n") : [];
  return {
    plus: lignes.filter((l) => l.startsWith("+")).length,
    moins: lignes.filter((l) => l.startsWith("-")).length,
  };
}

export function nombreLignes(texte) {
  if (!texte) return "fichier vide";
  const n = texte.replace(/\n$/, "").split("\n").length;
  return `${n} ligne${n > 1 ? "s" : ""}`;
}
