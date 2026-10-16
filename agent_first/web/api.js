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
