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

export function metaMessage(message) {
  return [
    "Gemini",
    message.modele,
    message.niveau && `réflexion ${message.niveau}`,
    message.duree != null && formaterDuree(message.duree),
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

// Ce que Gemini sait créer en plus du texte (menu « Créer » de la zone de saisie).
export const OUTILS = {
  image: { nom: "Image", icone: "i-image", attente: "Gemini crée l'image…", saisie: "Décris l'image à créer…", type: "image", article: "d'image" },
  video: { nom: "Vidéo", icone: "i-video", attente: "Gemini crée la vidéo… (souvent plusieurs minutes)", saisie: "Décris la vidéo à créer…", type: "video", article: "de vidéo" },
  musique: { nom: "Musique", icone: "i-musique", attente: "Gemini compose la musique…", saisie: "Décris la musique à créer…", type: "audio", article: "de musique" },
};

// Le texte d'attente pendant que Gemini travaille.
export function texteAttente(outil) {
  return OUTILS[outil]?.attente ?? "Gemini réfléchit…";
}

// L'outil d'un message de l'utilisateur (gardé dans ses détails), ou null.
export function outilDuMessage(message) {
  try {
    return JSON.parse(message.details ?? "null")?.outil ?? null;
  } catch {
    return null;
  }
}

// Un avertissement quand le média demandé n'est pas arrivé, ou null.
export function avertissementMedia(outil, medias = [], perdus = 0) {
  const recus = medias.filter((m) => m.type === OUTILS[outil]?.type).length;
  if (perdus) return `Médias vus dans Gemini mais non récupérés : ${perdus} (détails dans journaux/agent_first.log).`;
  if (outil && !recus) {
    return `Gemini n'a pas renvoyé ${OUTILS[outil].article} : il a pu refuser la demande, ou ce modèle ne sait pas en créer. Reformule, ou choisis un autre modèle.`;
  }
  return null;
}

// « 1 234 567 » octets → « 1,2 Mo ».
export function tailleFichier(octets) {
  if (octets == null) return "";
  if (octets < 1024) return `${octets} o`;
  const unites = ["Ko", "Mo", "Go"];
  let valeur = octets / 1024;
  let i = 0;
  while (valeur >= 1024 && i < unites.length - 1) {
    valeur /= 1024;
    i += 1;
  }
  return `${valeur.toLocaleString("fr-FR", { maximumFractionDigits: valeur < 10 ? 1 : 0 })} ${unites[i]}`;
}
