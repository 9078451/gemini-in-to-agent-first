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

test("NDJSON lu par morceaux coupés au milieu d'une ligne", async () => {
  const { lireNdjson } = await import("../../agent_first/web/outils.js");
  let r = lireNdjson("", '{"type":"partiel","texte":"Bon"}\n{"type":"par');
  assert.deepEqual(r.evenements, [{ type: "partiel", texte: "Bon" }]);
  r = lireNdjson(r.reste, 'tiel","texte":"Bonjour"}\n\n');
  assert.deepEqual(r.evenements, [{ type: "partiel", texte: "Bonjour" }]);
  assert.equal(r.reste, "");
});

test("détails d'un message", async () => {
  const { detailsMessage } = await import("../../agent_first/web/outils.js");
  assert.deepEqual(detailsMessage({ details: '{"interrompue": true}' }), { interrompue: true });
  assert.deepEqual(detailsMessage({ details: null }), {});
  assert.deepEqual(detailsMessage({ details: "{abîmé" }), {});
});

test("pied d'un message : fournisseur, modèle, interrompue", async () => {
  const { metaMessage } = await import("../../agent_first/web/outils.js");
  assert.equal(metaMessage({ fournisseur: "anthropic", modele: "claude-opus-5-5", duree: 3 }), "Claude · claude-opus-5-5 · 3 s");
  assert.equal(metaMessage({ fournisseur: "mistral", modele: "m", duree: null }, { mistral: "Mistral" }), "Mistral · m");
  assert.equal(metaMessage({ fournisseur: "claude_web", modele: "Par défaut" }), "Claude.ai");
  assert.equal(metaMessage({ modele: "x", details: '{"interrompue": true}' }), "Gemini · x · interrompue");
});

test("secours et état en clair", async () => {
  const { texteSecours, libelleEtat } = await import("../../agent_first/web/outils.js");
  assert.equal(texteSecours({ details: '{"secours": {"de": "gemini", "raison": "limite"}}' }), "secours · Gemini à sa limite");
  assert.equal(texteSecours({ details: null }), null);
  assert.equal(libelleEtat("limite", "jusqu'à 2:58 PM"), "limite · jusqu'à 2:58 PM");
  assert.equal(libelleEtat("pret"), "");
  assert.equal(libelleEtat("panne"), "en panne");
});

test("choix valide parmi les fournisseurs actifs", async () => {
  const { choixValide } = await import("../../agent_first/web/outils.js");
  const actifs = [
    { id: "gemini", modeles: [{ nom: "4 Argon", actif: true }, { nom: "3.8 Flash" }], niveaux: [{ nom: "Min.", actif: true }, { nom: "Max." }] },
    { id: "ollama", modeles: [{ nom: "llama3.2", actif: true }], niveaux: [] },
  ];
  assert.deepEqual(choixValide(actifs, { fournisseur: "gemini", modele: "3.8 Flash", niveau: "Max." }),
    { fournisseur: "gemini", modele: "3.8 Flash", niveau: "Max." });
  assert.deepEqual(choixValide(actifs, { fournisseur: "ollama", modele: "absent", niveau: "Max." }),
    { fournisseur: "ollama", modele: "llama3.2", niveau: null });
  assert.deepEqual(choixValide(actifs, { fournisseur: "mistral" }), { fournisseur: "gemini", modele: "4 Argon", niveau: "Min." });
  assert.deepEqual(choixValide([], {}), { fournisseur: null, modele: null, niveau: null });
});

test("palette : actions et conversations filtrées", async () => {
  const { filtrerPalette } = await import("../../agent_first/web/outils.js");
  const actions = [{ titre: "Nouvelle conversation" }, { titre: "Paramètres" }];
  const conversations = [{ titre: "Script de sauvegarde" }, { titre: "Résumé" }];
  assert.equal(filtrerPalette(actions, conversations, "").length, 4);
  assert.deepEqual(filtrerPalette(actions, conversations, "sauve").map((x) => x.titre), ["Script de sauvegarde"]);
  assert.deepEqual(filtrerPalette(actions, conversations, "PARAM").map((x) => x.titre), ["Paramètres"]);
});
