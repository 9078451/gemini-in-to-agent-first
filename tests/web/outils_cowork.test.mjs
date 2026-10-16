import { test } from "node:test";
import assert from "node:assert/strict";
import { estDangereuse, libelleEtape } from "../../agent_first/web/outils_cowork.js";

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
