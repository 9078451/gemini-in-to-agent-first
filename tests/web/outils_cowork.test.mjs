import { test } from "node:test";
import assert from "node:assert/strict";
import {
  avancementPlan,
  detailTour,
  estDangereuse,
  infoResultat,
  libelleEtape,
  lignesBilan,
  nombreLignes,
  normaliserAction,
  resumeDiff,
} from "../../agent_first/web/outils_cowork.js";

test("libellé d'une étape de création", () => {
  const e = libelleEtape({ type: "action", action: "create", champs: { path: "a.html" } });
  assert.equal(e.verbe, "Write");
  assert.match(e.titre, /créé|création/i);
  assert.equal(e.detail, "a.html");
});

test("ancien nom français : même libellé", () => {
  const ancien = libelleEtape({ type: "action", action: "creer", champs: { chemin: "a.html" } });
  assert.equal(ancien.verbe, "Write");
  assert.equal(ancien.detail, "a.html");
  assert.equal(libelleEtape({ type: "action", action: "commande", champs: { texte: "dir" } }).detail, "dir");
});

test("normaliser une action ancienne", () => {
  assert.deepEqual(normaliserAction({ action: "modifier", champs: { chemin: "a", avant: "x", apres: "y" } }), {
    action: "edit",
    champs: { path: "a", old: "x", new: "y" },
  });
});

test("libellé d'une commande", () => {
  const e = libelleEtape({ type: "action", action: "run", champs: { command: "dir" } });
  assert.match(e.titre, /commande/i);
  assert.equal(e.detail, "dir");
});

test("une demande est dangereuse", () => {
  assert.equal(estDangereuse({ type: "demande", raison: "suppression" }), true);
  assert.equal(estDangereuse({ type: "action", action: "read" }), false);
});

test("verbe court de chaque action, comme dans un terminal", () => {
  const verbe = (action) => libelleEtape({ type: "action", action, champs: {} }).verbe;
  const attendus = { list: "List", read: "Read", search: "Search", create: "Write", edit: "Edit", delete: "Delete",
    run: "Run", start: "Start", logs: "Logs", stop: "Stop", visit: "Visit" };
  for (const [action, v] of Object.entries(attendus)) assert.equal(verbe(action), v);
  assert.equal(verbe("modifier"), "Edit");
  assert.equal(verbe("inconnue"), "inconnue");
});

test("détails : url pour visit, numéro pour stop", () => {
  assert.equal(libelleEtape({ type: "action", action: "visit", champs: { url: "http://localhost:8080/" } }).detail, "http://localhost:8080/");
  assert.equal(libelleEtape({ type: "action", action: "stop", champs: { id: "1" } }).detail, "#1");
});

test("nouveaux types d'étape ont un titre", () => {
  for (const type of ["saute", "relance_fin", "question", "erreur_format", "plan"]) {
    assert.notEqual(libelleEtape({ type }).titre, type, type);
  }
});

test("résumé d'un diff : lignes ajoutées et retirées, sans le contexte", () => {
  assert.deepEqual(resumeDiff("-a\n+b\n+c"), { plus: 2, moins: 1 });
  assert.deepEqual(resumeDiff("@@ -1,3 +1,3 @@\n un\n-deux\n+trois\n quatre"), { plus: 1, moins: 1 });
  assert.deepEqual(resumeDiff("--- a\n+++ b\n+x"), { plus: 1, moins: 0 });
  assert.deepEqual(resumeDiff(""), { plus: 0, moins: 0 });
});

test("nombre de lignes d'un contenu écrit", () => {
  assert.equal(nombreLignes("a\nb\nc"), "3 lignes");
  assert.equal(nombreLignes("a"), "1 ligne");
  assert.equal(nombreLignes(""), "fichier vide");
});

test("avancement du plan", () => {
  assert.deepEqual(avancementPlan([{ fait: true }, { fait: false }]), { faites: 1, total: 2 });
  assert.deepEqual(avancementPlan([]), { faites: 0, total: 0 });
});

test("bilan : compteurs et fichiers", () => {
  const { compteurs, fichiers } = lignesBilan({
    crees: ["a"], modifies: ["b"], supprimes: [], commandes: [{ texte: "x", code: 1 }, { texte: "y", code: 0 }],
    verifications: 2, plan_inacheve: [], processus: [],
  });
  assert.match(compteurs, /1 créé/);
  assert.match(compteurs, /1 modifié/);
  assert.match(compteurs, /0 supprimé/);
  assert.match(compteurs, /2 vérifications/);
  assert.match(compteurs, /1 en échec/);
  assert.deepEqual(fichiers, [{ signe: "+", chemin: "a" }, { signe: "~", chemin: "b" }]);
});

test("bilan sans échec ni vérification", () => {
  const { compteurs } = lignesBilan({ crees: [], modifies: [], supprimes: ["c"], commandes: [], verifications: 0 });
  assert.match(compteurs, /1 supprimé/);
  assert.doesNotMatch(compteurs, /échec/);
  assert.match(compteurs, /aucune vérification/);
});

test("info d'un résultat selon l'action", () => {
  assert.equal(infoResultat("visit", "HTTP 500 text/html 10 bytes\n…"), "500");
  assert.equal(infoResultat("start", "started #2 (pid 123)\n…"), "#2");
  assert.equal(infoResultat("read", "a\nb"), "2 lignes");
  assert.equal(infoResultat("list", "a.txt\nd/"), "2 entrées");
  assert.equal(infoResultat("run", "ok"), "");
});

test("libellé quand Gemini répond par sa propre erreur", () => {
  const e = libelleEtape({ type: "erreur_gemini", corps: "Sorry, something went wrong." });
  assert.match(e.titre, /Gemini/);
  assert.match(e.titre, /renvoy/);
});

test("une réponse de Gemini et son temps", () => {
  assert.equal(detailTour({ type: "tour", gemini: 14.2 }), "Gemini a répondu en 14 s");
  assert.equal(libelleEtape({ type: "tour", gemini: 14.2 }).titre, "Réponse de Gemini");
});

test("bilan : les temps de Gemini et des actions", () => {
  const { compteurs } = lignesBilan({ crees: [], modifies: [], supprimes: [], commandes: [], verifications: 1,
    temps: { gemini: 73.4, actions: 5.1 } });
  assert.match(compteurs, /Gemini 73 s · actions 5 s/);
});

test("conversation Gemini neuve : un libellé clair", () => {
  assert.match(libelleEtape({ type: "relais", corps: "x" }).titre, /Nouvelle conversation Gemini/);
});
