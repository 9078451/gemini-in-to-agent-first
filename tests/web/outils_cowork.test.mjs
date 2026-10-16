import { test } from "node:test";
import assert from "node:assert/strict";
import { estDangereuse, libelleEtape, nombreLignes, resumeDiff } from "../../agent_first/web/outils_cowork.js";

test("libellé d'une étape de création", () => {
  const e = libelleEtape({ type: "action", action: "creer", champs: { chemin: "a.html" } });
  assert.match(e.titre, /créé|création/i);
  assert.equal(e.detail, "a.html");
});

test("libellé d'une commande", () => {
  const e = libelleEtape({ type: "action", action: "commande", champs: { texte: "dir" } });
  assert.match(e.titre, /commande/i);
  assert.equal(e.detail, "dir");
});

test("une demande est dangereuse", () => {
  assert.equal(estDangereuse({ type: "demande", raison: "suppression" }), true);
  assert.equal(estDangereuse({ type: "action", action: "lire" }), false);
});

test("verbe court de chaque action, comme dans un terminal", () => {
  const verbe = (action) => libelleEtape({ type: "action", action, champs: {} }).verbe;
  assert.equal(verbe("creer"), "Write");
  assert.equal(verbe("modifier"), "Edit");
  assert.equal(verbe("lire"), "Read");
  assert.equal(verbe("commande"), "Shell");
  assert.equal(verbe("inconnue"), "inconnue");
});

test("résumé d'un diff : lignes ajoutées et retirées", () => {
  assert.deepEqual(resumeDiff("-a\n+b\n+c"), { plus: 2, moins: 1 });
  assert.deepEqual(resumeDiff(""), { plus: 0, moins: 0 });
});

test("nombre de lignes d'un contenu écrit", () => {
  assert.equal(nombreLignes("a\nb\nc"), "3 lignes");
  assert.equal(nombreLignes("a"), "1 ligne");
  assert.equal(nombreLignes(""), "fichier vide");
});
