// Fonctions pures de l'app (sans DOM), testées avec `node --test tests/web/`.

const LONGUEUR_TITRE = 60;
const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

function debutDuJour(date, decalageJours = 0) {
  const jour = new Date(date);
  jour.setHours(0, 0, 0, 0);
  jour.setDate(jour.getDate() + decalageJours);
  return jour.getTime();
}

export function groupesParDate(conversations, maintenant = new Date()) {
  const groupes = [
    { titre: "Aujourd'hui", depuis: debutDuJour(maintenant) },
    { titre: "Hier", depuis: debutDuJour(maintenant, -1) },
    { titre: "7 derniers jours", depuis: debutDuJour(maintenant, -6) },
    { titre: "Plus ancien", depuis: -Infinity },
  ].map((groupe) => ({ ...groupe, conversations: [] }));
  for (const conversation of conversations) {
    const quand = new Date(conversation.modifie_le).getTime();
    groupes.find((groupe) => quand >= groupe.depuis).conversations.push(conversation);
  }
  return groupes
    .filter((groupe) => groupe.conversations.length)
    .map(({ titre, conversations: liste }) => ({ titre, conversations: liste }));
}

export function formaterDuree(secondes) {
  if (secondes == null) return "";
  const total = Math.round(secondes);
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  const reste = total % 60;
  return reste ? `${minutes} min ${reste} s` : `${minutes} min`;
}

export function formaterDate(iso, maintenant = new Date()) {
  const date = new Date(iso);
  const heure = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  const jour = debutDuJour(date);
  if (jour === debutDuJour(maintenant)) return `aujourd'hui ${heure}`;
  if (jour === debutDuJour(maintenant, -1)) return `hier ${heure}`;
  const texte = `${date.getDate()} ${MOIS[date.getMonth()]}`;
  return date.getFullYear() === new Date(maintenant).getFullYear() ? texte : `${texte} ${date.getFullYear()}`;
}

export function titreDepuis(texte) {
  const titre = texte.split(/\s+/).filter(Boolean).join(" ");
  return titre.length <= LONGUEUR_TITRE ? titre : `${titre.slice(0, LONGUEUR_TITRE - 1)}…`;
}

// Noms affichés des fournisseurs connus d'avance ; les autres viennent d'Agent First (`noms`).
const NOMS = { gemini: "Gemini", chatgpt: "ChatGPT", claude_web: "Claude.ai", anthropic: "Claude", ollama: "Ollama" };

export function nomFournisseur(id, noms = {}) {
  return noms[id] ?? NOMS[id] ?? id ?? "Gemini";
}

export function metaMessage(message, noms = {}) {
  return [
    nomFournisseur(message.fournisseur ?? "gemini", noms),
    message.modele && message.modele !== "Par défaut" ? message.modele : null,
    message.niveau && `réflexion ${message.niveau}`,
    message.duree != null && formaterDuree(message.duree),
    detailsMessage(message).interrompue && "interrompue",
  ]
    .filter(Boolean)
    .join(" · ");
}

// Option (modèle ou niveau) bloquée par la limite du compte : Gemini remplace sa description
// par « Réinitialisation de la limite : 16 oct., 14:58 ». Renvoie ce moment, sinon null.
export function limiteOption(option) {
  const trouve = (option.description ?? "").replace(/\s+/g, " ").match(/^\s*Réinitialisation de la limite\s*:\s*(.+?)\s*$/);
  return trouve ? trouve[1] : null;
}

// Le choix à afficher : `nom` s'il existe et n'est pas bloqué ; sinon l'option active, ou la
// première, parmi celles qui sont libres. Si tout est bloqué, on garde `nom` (ou l'active) :
// Gemini dira alors clairement jusqu'à quand.
export function choixDisponible(liste, nom) {
  const libres = liste.filter((o) => !limiteOption(o));
  if (libres.some((o) => o.nom === nom)) return nom;
  const repli = libres.find((o) => o.actif) ?? libres[0];
  if (repli) return repli.nom;
  if (liste.some((o) => o.nom === nom)) return nom;
  return (liste.find((o) => o.actif) ?? liste[0])?.nom ?? null;
}

// « C:\Users\nom\Desktop\site » → « ~\Desktop\site » ; les autres chemins restent tels quels.
export function cheminCourt(chemin) {
  return chemin.replace(/^[A-Za-z]:\\Users\\[^\\]+(?=\\|$)/i, "~");
}

// Flux NDJSON (une ligne JSON par évènement) lu par morceaux : un morceau peut couper une
// ligne en deux. Renvoie les évènements complets et le reste, à compléter par le morceau suivant.
export function lireNdjson(reste, morceau) {
  const lignes = (reste + morceau).split("\n");
  const fin = lignes.pop();
  return { evenements: lignes.filter((l) => l.trim()).map((l) => JSON.parse(l)), reste: fin };
}

// Détails d'un message du Chat (JSON) : { interrompue, secours… } ; {} s'ils manquent ou sont illisibles.
export function detailsMessage(message) {
  try {
    return JSON.parse(message.details || "{}") ?? {};
  } catch {
    return {};
  }
}

// « secours · Gemini à sa limite » : la réponse vient du fournisseur de secours.
const RAISONS = { limite: "à sa limite", deconnecte: "déconnecté", panne: "en panne" };

export function texteSecours(message, noms = {}) {
  const secours = detailsMessage(message).secours;
  if (!secours) return null;
  return `secours · ${nomFournisseur(secours.de, noms)} ${RAISONS[secours.raison] ?? "indisponible"}`;
}

// État d'un fournisseur, en clair (rien quand il est inconnu ou prêt : le point suffit).
export function libelleEtat(etat, detail) {
  if (etat === "limite") return detail ? `limite · ${detail}` : "limite";
  if (etat === "deconnecte") return "déconnecté";
  if (etat === "panne") return "en panne";
  return "";
}

// Le réglage à utiliser parmi les fournisseurs actifs : le préféré s'il existe encore
// (fournisseur, puis modèle et niveau libres), sinon le premier fournisseur et son choix actif.
export function choixValide(fournisseurs, prefere = {}) {
  const f = fournisseurs.find((x) => x.id === prefere.fournisseur) ?? fournisseurs[0];
  if (!f) return { fournisseur: null, modele: null, niveau: null };
  const memeFournisseur = f.id === prefere.fournisseur;
  return {
    fournisseur: f.id,
    modele: f.modeles.length ? choixDisponible(f.modeles, memeFournisseur ? prefere.modele : null) : null,
    niveau: f.niveaux.length ? choixDisponible(f.niveaux, prefere.niveau) : null,
  };
}

// Palette Ctrl K : les actions puis les conversations dont le titre contient le texte cherché.
export function filtrerPalette(actions, conversations, texte) {
  const motif = texte.trim().toLowerCase();
  const garde = (t) => !motif || t.toLowerCase().includes(motif);
  return [...actions.filter((a) => garde(a.titre)), ...conversations.filter((c) => garde(c.titre || ""))];
}
