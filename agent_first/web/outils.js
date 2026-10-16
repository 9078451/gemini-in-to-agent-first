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
