// Libellés des étapes Cowork (fonctions pures, testées avec `node --test tests/web/`).

const ACTIONS = {
  lister: { icone: "i-dossier", titre: "Dossier listé", champ: "chemin" },
  lire: { icone: "i-fichier", titre: "Fichier lu", champ: "chemin" },
  chercher: { icone: "i-recherche", titre: "Recherche", champ: "motif" },
  creer: { icone: "i-fichier", titre: "Fichier créé", champ: "chemin" },
  modifier: { icone: "i-crayon", titre: "Fichier modifié", champ: "chemin" },
  supprimer: { icone: "i-corbeille", titre: "Suppression", champ: "chemin" },
  commande: { icone: "i-terminal", titre: "Commande", champ: "texte" },
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
    const a = ACTIONS[ev.action] ?? { icone: "i-etincelle", titre: ev.action, champ: null };
    return { icone: a.icone, titre: a.titre, detail: a.champ ? (ev.champs?.[a.champ] ?? "") : "" };
  }
  const autre = AUTRES[ev.type] ?? { icone: "i-etincelle", titre: ev.type };
  return { icone: autre.icone, titre: autre.titre, detail: ev.raison ?? ev.resume ?? ev.corps ?? "" };
}

export function estDangereuse(ev) {
  return ev.type === "demande";
}
