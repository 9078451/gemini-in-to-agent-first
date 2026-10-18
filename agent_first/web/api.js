// Appels à l'API d'Agent First. Lève une Error dont le message s'affiche tel quel.

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

// Comme `appeler`, mais la réponse arrive ligne à ligne (NDJSON) : `surLigne` reçoit chaque
// évènement ({type: "texte" | "fin" | "erreur" | "arrete", …}) ; renvoie le dernier.
export async function appelerEnDirect(chemin, corps, surLigne) {
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
  if (!reponse.ok || !reponse.body) {
    let contenu = {};
    try {
      contenu = await reponse.json();
    } catch {
      // réponse vide ou illisible : le code HTTP suffit
    }
    throw new Error(contenu.erreur || `Erreur d'Agent First (code ${reponse.status}).`);
  }
  const lecteur = reponse.body.getReader();
  const decodeur = new TextDecoder();
  let reste = "";
  let dernier = null;
  for (;;) {
    let morceau;
    try {
      morceau = await lecteur.read();
    } catch {
      throw new Error("Agent First n'est pas démarré.");
    }
    reste += decodeur.decode(morceau.value ?? new Uint8Array(), { stream: !morceau.done });
    const lignes = reste.split("\n");
    reste = morceau.done ? "" : lignes.pop();
    for (const ligne of lignes) {
      if (!ligne.trim()) continue;
      dernier = JSON.parse(ligne);
      surLigne(dernier);
    }
    if (morceau.done) return dernier;
  }
}
