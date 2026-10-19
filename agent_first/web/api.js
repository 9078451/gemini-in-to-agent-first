// Appels à l'API d'Agent First. Lève une Error dont le message s'affiche tel quel.
import { lireNdjson } from "./outils.js";

// POST dont la réponse arrive en NDJSON : `surEvenement` reçoit chaque évènement dès qu'il arrive.
export async function appelerFlux(chemin, corps, surEvenement) {
  let reponse;
  try {
    reponse = await fetch(chemin, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corps),
    });
  } catch {
    throw new Error("Agent First n'est pas démarré.");
  }
  if (!reponse.ok) {
    let contenu = {};
    try {
      contenu = await reponse.json();
    } catch {
      // réponse vide ou illisible : le code HTTP suffit
    }
    throw new Error(contenu.erreur || `Erreur d'Agent First (code ${reponse.status}).`);
  }
  const lecteur = reponse.body.pipeThrough(new TextDecoderStream()).getReader();
  let reste = "";
  for (;;) {
    let lu;
    try {
      lu = await lecteur.read();
    } catch {
      throw new Error("Connexion à Agent First coupée pendant la réponse.");
    }
    if (lu.done) break;
    const r = lireNdjson(reste, lu.value);
    reste = r.reste;
    r.evenements.forEach(surEvenement);
  }
}

export async function appeler(methode, chemin, corps) {
  let reponse;
  try {
    reponse = await fetch(chemin, {
      method: methode,
      headers: corps ? { "Content-Type": "application/json" } : {},
      body: corps ? JSON.stringify(corps) : undefined,
    });
  } catch {
    throw new Error("Agent First n'est pas démarré.");
  }
  let contenu = {};
  try {
    contenu = await reponse.json();
  } catch {
    // réponse vide ou illisible : le code HTTP suffit
  }
  if (!reponse.ok) {
    throw new Error(contenu.erreur || `Erreur d'Agent First (code ${reponse.status}).`);
  }
  return contenu;
}
