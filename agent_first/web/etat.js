// L'état de l'app, partagé par ses modules.
import { nomFournisseur } from "./outils.js";

export const etat = {
  fournisseurs: [], // fournisseurs actifs : id, nom, type, etat, detail, modeles, niveaux
  tous: [], // tous les fournisseurs connus, avec leurs réglages (clés masquées)
  secours: { actif: false, fournisseur: null, modele: null },
  choix: { fournisseur: "gemini", modele: null, niveau: null }, // réglage de la zone de saisie
  courante: null, // identifiant de la conversation affichée ; null = nouvelle conversation
  conversation: null, // la conversation affichée (titre, fournisseur…)
  occupe: false, // un message ou une tâche est en cours dans la conversation affichée
  reponseEnCours: false, // réponse du Chat en cours (le bouton Arrêter la coupe)
  periode: "7j",
  serveur: null, // dernière réponse de /api/etat (null = Agent First injoignable)
  mode: "chat", // « chat » ou « cowork »
  dossier: null, // dossier de travail (mode Cowork)
  tache: null, // conversation dont une tâche Cowork est suivie en direct
  flux: null, // EventSource de cette tâche
  actives: new Set(), // conversations dont une tâche tourne (app ou API réseau)
  attentes: new Set(), // conversations dont une tâche attend un accord
};

export function noms() {
  return Object.fromEntries(etat.tous.map((f) => [f.id, f.nom]));
}

export function nom(id) {
  return nomFournisseur(id, noms());
}

export function fournisseur(id) {
  return etat.fournisseurs.find((f) => f.id === id) ?? null;
}
