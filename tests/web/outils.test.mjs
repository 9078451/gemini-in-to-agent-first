import { test } from "node:test";
import assert from "node:assert/strict";
import { cheminCourt, choixDisponible, formaterDate, limiteOption, formaterDuree, groupesParDate, metaMessage, titreDepuis } from "../../agent_first/web/outils.js";

const maintenant = new Date(2026, 9, 16, 14, 30); // 16 oct. 2026, 14:30 (heure locale)
const iso = (jour, heure = 12, minute = 0, mois = 10, annee = 2026) =>
  `${annee}-${String(mois).padStart(2, "0")}-${String(jour).padStart(2, "0")}T${String(heure).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00`;

test("groupes par date, sans groupe vide", () => {
  const conversations = [
    { id: "a", modifie_le: iso(16, 9) },
    { id: "b", modifie_le: iso(15, 23, 59) },
    { id: "c", modifie_le: iso(12) },
    { id: "d", modifie_le: iso(1) },
  ];
  assert.deepEqual(
    groupesParDate(conversations, maintenant).map((g) => [g.titre, g.conversations.map((c) => c.id)]),
    [["Aujourd'hui", ["a"]], ["Hier", ["b"]], ["7 derniers jours", ["c"]], ["Plus ancien", ["d"]]],
  );
  assert.deepEqual(groupesParDate([{ id: "a", modifie_le: iso(16) }], maintenant).map((g) => g.titre), ["Aujourd'hui"]);
});

test("7 derniers jours : du 10 au 14 octobre", () => {
  const groupes = groupesParDate([{ id: "x", modifie_le: iso(10) }, { id: "y", modifie_le: iso(9, 23) }], maintenant);
  assert.deepEqual(groupes.map((g) => g.titre), ["7 derniers jours", "Plus ancien"]);
});

test("durées", () => {
  assert.equal(formaterDuree(null), "");
  assert.equal(formaterDuree(12.4), "12 s");
  assert.equal(formaterDuree(75), "1 min 15 s");
  assert.equal(formaterDuree(120), "2 min");
});

test("dates", () => {
  assert.equal(formaterDate(iso(16, 9, 5), maintenant), "aujourd'hui 09:05");
  assert.equal(formaterDate(iso(15, 18), maintenant), "hier 18:00");
  assert.equal(formaterDate(iso(12), maintenant), "12 oct.");
  assert.equal(formaterDate(iso(3, 12, 0, 3, 2025), maintenant), "3 mars 2025");
});

test("titre sur une ligne, coupé à 60 caractères", () => {
  assert.equal(titreDepuis("Ligne 1\nLigne 2"), "Ligne 1 Ligne 2");
  const long = titreDepuis("mot ".repeat(40));
  assert.equal(long.length, 60);
  assert.ok(long.endsWith("…"));
});

test("ligne d'information d'une réponse", () => {
  assert.equal(metaMessage({ modele: "4 Argon", niveau: "Max.", duree: 12 }), "Gemini · 4 Argon · réflexion Max. · 12 s");
  assert.equal(metaMessage({ modele: null, niveau: null, duree: null }), "Gemini");
});

test("chemin court : le dossier de l'utilisateur devient ~", () => {
  assert.equal(cheminCourt("C:\\Users\\thoma\\Desktop\\mon-site"), "~\\Desktop\\mon-site");
  assert.equal(cheminCourt("C:\\Users\\thoma"), "~");
  assert.equal(cheminCourt("D:\\projets\\site"), "D:\\projets\\site");
});

test("option bloquée par la limite du compte Gemini", () => {
  assert.equal(limiteOption({ nom: "4 Argon", description: "Réinitialisation de la limite : 16 oct., 14:58" }), "16 oct., 14:58");
  assert.equal(limiteOption({ nom: "3.5 Flash-Lite", description: "Réponses les plus rapides" }), null);
  assert.equal(limiteOption({ nom: "Min.", description: "" }), null);
});

test("réglage par défaut bloqué : on prend un choix disponible", () => {
  const bloque = "Réinitialisation de la limite : 16 oct., 14:58";
  const liste = [
    { nom: "3.5 Flash-Lite", description: "Réponses les plus rapides", actif: true },
    { nom: "4 Argon", description: bloque, actif: false },
  ];
  assert.equal(choixDisponible(liste, "4 Argon"), "3.5 Flash-Lite");
  assert.equal(choixDisponible(liste, "3.5 Flash-Lite"), "3.5 Flash-Lite");
  assert.equal(choixDisponible(liste, "inconnu"), "3.5 Flash-Lite");
  assert.equal(choixDisponible([{ nom: "Max.", description: bloque, actif: true }], "Max."), "Max.");
  assert.equal(choixDisponible([], "Min."), null);
});

test("création de médias : attente, outil du message, avertissement, taille", async () => {
  const { texteAttente, outilDuMessage, avertissementMedia, tailleFichier } = await import("../../agent_first/web/outils.js");
  assert.equal(texteAttente(null), "Gemini réfléchit…");
  assert.match(texteAttente("video"), /vidéo/);
  assert.equal(outilDuMessage({ details: '{"outil": "image"}' }), "image");
  assert.equal(outilDuMessage({ details: null }), null);
  assert.equal(outilDuMessage({ details: "{cassé" }), null);
  assert.equal(avertissementMedia(null, []), null);
  assert.equal(avertissementMedia("image", [{ type: "image" }]), null);
  assert.match(avertissementMedia("image", []), /pas renvoyé d'image/);
  assert.match(avertissementMedia("musique", [{ type: "image" }]), /pas renvoyé de musique/);
  assert.match(avertissementMedia(null, [], 2), /non récupérés : 2/);
  assert.equal(tailleFichier(512), "512 o");
  assert.equal(tailleFichier(1536), "1,5 Ko");
  assert.equal(tailleFichier(25 * 1024 * 1024), "25 Mo");
});

test("pièces jointes : limites et refus expliqués", async () => {
  const { trierPieces, MAX_OCTETS_PIECE, estInterrompue } = await import("../../agent_first/web/outils.js");
  const f = (name, size) => ({ name, size });
  const { acceptees, refus } = trierPieces(9, [f("a.png", 10), f("b.png", 10), f("gros.mp4", MAX_OCTETS_PIECE + 1), f("vide.txt", 0)]);
  assert.deepEqual(acceptees.map((x) => x.name), ["a.png"]);
  assert.equal(refus.length, 3);
  assert.match(refus[0], /^b\.png : 10 fichiers au plus/);
  assert.match(refus[1], /^gros\.mp4 : plus de 50 Mo/);
  assert.equal(estInterrompue({ details: '{"interrompue": true}' }), true);
  assert.equal(estInterrompue({ details: null }), false);
});

test("plusieurs assistants : nom, relais, outils possibles", async () => {
  const { fournisseurDuMessage, libelleDe, metaMessage, outilPossible, texteAttente, texteRelais, avertissementMedia } = await import("../../agent_first/web/outils.js");
  const fournisseurs = [{ nom: "gemini", libelle: "Gemini", outils: ["image", "video", "musique"] }, { nom: "chatgpt", libelle: "ChatGPT", outils: ["image"] }, { nom: "claude", libelle: "Claude", outils: [] }];
  assert.equal(fournisseurDuMessage({ details: '{"fournisseur": "chatgpt"}' }), "chatgpt");
  assert.equal(fournisseurDuMessage({ details: null }), "gemini");
  assert.equal(fournisseurDuMessage({ details: "{cassé" }), "gemini");
  assert.equal(libelleDe(fournisseurs, "chatgpt"), "ChatGPT");
  assert.equal(libelleDe(fournisseurs, "grok"), "Grok"); // pas encore chargé : son nom, en majuscule
  assert.equal(metaMessage({ modele: "Thinking", niveau: null, duree: 3 }, "ChatGPT"), "ChatGPT · Thinking · 3 s");
  assert.equal(texteAttente(null, "Claude"), "Claude réfléchit…");
  assert.equal(texteAttente("image", "ChatGPT"), "ChatGPT crée l'image…");
  assert.match(avertissementMedia("image", [], 0, "ChatGPT"), /^ChatGPT n'a pas renvoyé d'image/);
  assert.equal(outilPossible(fournisseurs[1], "image"), true);
  assert.equal(outilPossible(fournisseurs[1], "video"), false);
  assert.equal(outilPossible(fournisseurs[2], null), true);
  assert.equal(outilPossible(undefined, "image"), false);
  const relais = texteRelais({ texte: "Gemini → ChatGPT", details: JSON.stringify({ de: "Gemini", vers: "ChatGPT", raison: "limite" }) });
  assert.deepEqual(relais, { texte: "ChatGPT a pris le relais de Gemini", raison: "limite" });
  assert.deepEqual(texteRelais({ texte: "Gemini → ChatGPT", details: null }), { texte: "Gemini → ChatGPT", raison: "" });
});
