// Palette Ctrl K : chercher une conversation (titre et messages) ou lancer une action.
import { appeler } from "./api.js";
import { $, element, icone } from "./dom.js";
import { filtrerPalette, formaterDate } from "./outils.js";

let actions = [];
let ouvrirConversation = () => {};
let resultats = [];
let actif = 0;
let attente;
let demande = 0; // ignore une réponse arrivée après une frappe plus récente

export function brancherPalette({ actions: liste, ouvrir }) {
  actions = liste;
  ouvrirConversation = ouvrir;
  $("palette-saisie").addEventListener("input", () => {
    clearTimeout(attente);
    attente = setTimeout(chercher, 120);
  });
  $("palette-saisie").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      actif = Math.max(0, Math.min(resultats.length - 1, actif + (e.key === "ArrowDown" ? 1 : -1)));
      dessiner();
    } else if (e.key === "Enter") {
      e.preventDefault();
      executer(resultats[actif]);
    }
  });
  $("palette").addEventListener("click", (e) => {
    if (e.target === $("palette")) $("palette").close();
  });
}

export function ouvrirPalette() {
  $("palette-saisie").value = "";
  if (!$("palette").open) $("palette").showModal();
  $("palette-saisie").focus();
  chercher();
}

async function chercher() {
  const texte = $("palette-saisie").value;
  const numero = ++demande;
  let conversations = [];
  try {
    conversations = await appeler("GET", `/api/conversations?${new URLSearchParams({ recherche: texte.trim() })}`);
  } catch {
    // Agent First injoignable : seules les actions restent
  }
  if (numero !== demande) return;
  // La recherche d'Agent First regarde aussi le contenu des messages : on garde ses résultats.
  resultats = [
    ...filtrerPalette(actions, [], texte),
    ...conversations.slice(0, 30).map((c) => ({ conversation: c, titre: c.titre || "Sans titre" })),
  ];
  actif = 0;
  dessiner();
}

function executer(resultat) {
  if (!resultat) return;
  $("palette").close();
  if (resultat.conversation) ouvrirConversation(resultat.conversation.id);
  else resultat.faire();
}

function dessiner() {
  const liste = $("palette-liste");
  const lignes = [];
  let groupe = null;
  resultats.forEach((r, i) => {
    const nomGroupe = r.conversation ? "Conversations" : "Actions";
    if (nomGroupe !== groupe) {
      groupe = nomGroupe;
      lignes.push(element("div", "palette-groupe", nomGroupe));
    }
    const ligne = element("button", `palette-ligne${i === actif ? " actif" : ""}`);
    ligne.type = "button";
    ligne.setAttribute("role", "option");
    ligne.append(icone(r.conversation ? (r.conversation.mode === "cowork" ? "i-terminal" : "i-messages") : r.icone), element("span", "titre", r.titre));
    if (r.conversation) ligne.append(element("span", "infos", formaterDate(r.conversation.modifie_le)));
    else if (r.raccourci) ligne.append(element("kbd", null, r.raccourci));
    ligne.addEventListener("click", () => executer(r));
    ligne.addEventListener("mousemove", () => {
      if (actif === i) return;
      actif = i;
      liste.querySelectorAll(".palette-ligne").forEach((l) => l.classList.toggle("actif", l === ligne));
    });
    lignes.push(ligne);
  });
  if (!resultats.length) lignes.push(element("p", "vide", "Aucun résultat."));
  liste.replaceChildren(...lignes);
  liste.querySelector(".actif")?.scrollIntoView({ block: "nearest" });
}
