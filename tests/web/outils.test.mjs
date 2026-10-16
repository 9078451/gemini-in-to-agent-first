import { test } from "node:test";
import assert from "node:assert/strict";
import { formaterDate, formaterDuree, groupesParDate, metaMessage, titreDepuis } from "../../agent_first/web/outils.js";

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
