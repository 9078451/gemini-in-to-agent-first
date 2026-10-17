import json
import sys
import threading
import time

from fastapi.testclient import TestClient

from agent_first.cowork_service import ServiceCowork
from agent_first.diffuseur import Diffuseur
from agent_first.file_attente import FileAttente
from agent_first.historique import Historique
from agent_first.serveur import creer_app
from cowork.actions import Executeur
from cowork.boucle import Reglages
from cowork.processus import GestionnaireProcessus
from pilote.modeles import Modes, Option, ResultatGemini

PAR_DEFAUT = Modes([Option("4 Argon", "Tâches complexes")], [Option("Min.", "Rapide et efficace")])
REGLAGES = Reglages(max_tours=40, max_actions=10, echecs_max=3, taille_max=8000, taille_max_message=30000, relances_fin_max=2)


def bloc(*actions):
    return "```json\n" + json.dumps(list(actions) if len(actions) > 1 else actions[0], ensure_ascii=False) + "\n```"


FINI = bloc({"action": "done", "summary": "fait"})


class FauxPilote:
    """Renvoie des réponses Cowork scriptées et garde les textes reçus."""

    def __init__(self, reponses):
        self._reponses = list(reponses)
        self.textes = []
        self.delais = []

    def envoyer(self, adresse, texte, modele=None, niveau=None, delai=None):
        self.textes.append(texte)
        self.delais.append(delai)
        reponse = self._reponses.pop(0) if self._reponses else FINI
        return ResultatGemini(reponse=reponse, adresse="https://gemini.google.com/app/1")

    def est_connecte(self):
        return True

    def lister_modes(self):
        return PAR_DEFAUT


def fabrique_processus(dossier, au_changement):
    # Quelle que soit la commande demandée, un python qui dort : rien de réel n'est lancé.
    return GestionnaireProcessus(
        dossier, 3, 0.3, 8000, commande=lambda texte: [sys.executable, "-c", "import time; time.sleep(30)"],
        au_changement=au_changement,
    )


def fabrique_executeur(dossier, processus, arret):
    return Executeur(dossier, 5, 8000, lancer=lambda *a, **k: (0, "sortie"), processus=processus, arret=arret)


def service_sur(file, historique, diffuseur=None, **options):
    return ServiceCowork(file, historique, fabrique_executeur, REGLAGES, fabrique_processus, diffuseur=diffuseur, **options)


def monter(tmp_path, reponses, choisir=None, pilote=None, diffuseur=None, **options):
    pilote = pilote or FauxPilote(reponses)
    file = FileAttente(lambda: pilote)
    file.demarrer()
    historique = Historique(tmp_path / "historique.db")
    service = service_sur(file, historique, diffuseur, **options)
    app = creer_app(file, historique, 2.0, lambda: True, PAR_DEFAUT, cowork=service,
                    choisir_dossier=choisir or (lambda: str(tmp_path)), diffuseur=diffuseur)
    return TestClient(app), file, historique, service


def drainer_dans(service, conversation_id, sortie, depuis=0):
    """Empile chaque évènement du flux dans `sortie` dès son arrivée."""
    for ligne in service.flux(conversation_id, depuis):
        if ligne.startswith("data:"):
            sortie.append(json.loads(ligne[5:].strip()))


def evenements(service, conversation_id):
    sortie = []
    drainer_dans(service, conversation_id, sortie)
    return sortie


def types(evs):
    return [e["type"] for e in evs if e["type"] not in ("statut", "processus")]


def fin(evs):
    """Le dernier évènement qui compte (statut et processus ne font que passer)."""
    return [e for e in evs if e["type"] not in ("statut", "processus")][-1]


def attendre(collectes, type_, delai=5.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        trouve = next((e for e in collectes if e["type"] == type_), None)
        if trouve:
            return trouve
        time.sleep(0.05)
    raise AssertionError(f"pas d'évènement {type_} : {types(collectes)}")


def lancer_tache(client, service, conversation_id, texte):
    client.post(f"/api/cowork/{conversation_id}/messages", json={"texte": texte})
    return evenements(service, conversation_id)


def test_conversation_cowork_cree_avec_dossier(tmp_path):
    client, file, *_ = monter(tmp_path, [])
    r = client.post("/api/conversations", json={"mode": "cowork", "dossier": str(tmp_path)})
    assert (r.json()["mode"], r.json()["dossier"], r.json()["source"]) == ("cowork", str(tmp_path), "app")
    file.arreter()


def test_choisir_dossier(tmp_path):
    client, file, *_ = monter(tmp_path, [], choisir=lambda: str(tmp_path))
    assert client.post("/api/dossiers/choisir").json()["dossier"] == str(tmp_path)
    file.arreter()


def test_chaque_demande_part_avec_le_cadre(tmp_path):
    pilote = FauxPilote([FINI, FINI])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "première demande")
    lancer_tache(client, service, conv.id, "seconde demande")
    for texte, demande in zip(pilote.textes, ("première demande", "seconde demande")):
        assert texte.startswith("[AGENT FIRST · COWORK]") and f'USER REQUEST:\n"""\n{demande}\n"""' in texte
    file.arreter()


def test_cadre_construit_au_debut_reel_de_la_tache(tmp_path):
    # Un seul Chrome : une tâche peut attendre son tour. Son cadre montre le dossier
    # tel qu'il est quand elle commence, pas quand elle a été demandée.
    pilote = FauxPilote([FINI])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    libere = threading.Event()
    file.soumettre(lambda _pilote: libere.wait(5))  # une autre demande occupe Gemini
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "range"})
    (tmp_path / "arrive_entre_temps.txt").write_text("x", encoding="utf-8")
    libere.set()
    evenements(service, conv.id)
    assert "arrive_entre_temps.txt" in pilote.textes[0]
    file.arreter()


def test_tache_cree_un_fichier(tmp_path):
    client, file, historique, service = monter(tmp_path, [bloc({"action": "create", "path": "a.txt", "content": "salut"}), FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    evs = lancer_tache(client, service, conv.id, "crée a.txt")
    assert types(evs)[-1] == "termine"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "salut"
    file.arreter()


def test_bilan_dans_termine(tmp_path):
    client, file, historique, service = monter(tmp_path, [bloc({"action": "create", "path": "a.txt", "content": "x"}), FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    evs = lancer_tache(client, service, conv.id, "crée a.txt")
    assert fin(evs)["type"] == "termine" and fin(evs)["bilan"]["crees"] == ["a.txt"]
    file.arreter()


def test_derniere_tache_dans_le_cadre(tmp_path):
    pilote = FauxPilote([bloc({"action": "create", "path": "a.txt", "content": "x"}), FINI, FINI])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "crée a.txt")
    lancer_tache(client, service, conv.id, "et après ?")
    assert "LAST TASK: done" in pilote.textes[-1] and "a.txt" in pilote.textes[-1]
    assert "a.txt" in pilote.textes[-1].split("FOLDER CONTENT (")[1]
    file.arreter()


def test_etapes_enregistrees(tmp_path):
    client, file, historique, service = monter(tmp_path, [bloc({"action": "list"}), FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "liste")
    etapes = [json.loads(m["details"]) for m in client.get(f"/api/conversations/{conv.id}").json()["messages"]
              if m["role"] == "cowork"]
    assert [e["type"] for e in etapes] == ["action", "resultat", "termine"]  # ni statut ni processus
    file.arreter()


def test_decision_debloque_une_action_dangereuse(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"}), FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    collectes = []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime a.txt"})
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, collectes))
    fil.start()
    demande = attendre(collectes, "demande")
    client.post(f"/api/cowork/{conv.id}/decision", json={"etape": demande["etape"], "reponse": "continuer"})
    fil.join(timeout=5)
    assert not (tmp_path / "a.txt").exists()
    file.arreter()


def test_flux_apres_la_fin_rejoue_sans_bloquer(tmp_path):
    client, file, historique, service = monter(tmp_path, [FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    premier = lancer_tache(client, service, conv.id, "rien")
    second = []
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, second), daemon=True)
    fil.start()
    fil.join(timeout=2)  # une reconnexion du navigateur ne doit pas rester bloquée
    assert not fil.is_alive() and second == premier
    file.arreter()


def test_deux_lecteurs_du_flux(tmp_path):
    client, file, historique, service = monter(tmp_path, [bloc({"action": "list"}), FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    a, b = [], []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "liste"})
    fils = [threading.Thread(target=drainer_dans, args=(service, conv.id, s)) for s in (a, b)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=5)
    assert a == b and types(a)[-1] == "termine"
    file.arreter()


def test_flux_depuis(tmp_path):
    client, file, historique, service = monter(tmp_path, [bloc({"action": "list"}), FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    tout = lancer_tache(client, service, conv.id, "liste")
    suite = []
    drainer_dans(service, conv.id, suite, depuis=2)
    assert suite == tout[2:]
    file.arreter()


def test_question_puis_reponse_reprend_la_tache(tmp_path):
    pilote = FauxPilote([bloc({"action": "plan", "steps": ["[ ] a"]}, {"action": "ask", "question": "Quel port ?"})])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    evs = lancer_tache(client, service, conv.id, "fais un serveur")
    assert fin(evs)["type"] == "question" and fin(evs)["question"] == "Quel port ?"
    evs = lancer_tache(client, service, conv.id, "8080")
    assert 'USER ANSWER TO YOUR QUESTION:\n"""\n8080\n"""' in pilote.textes[1]
    assert "NOT FINISHED: unchecked plan steps: a" in pilote.textes[2]  # même plan : done refusé
    file.arreter()


def test_reprise_apres_redemarrage(tmp_path):
    pilote = FauxPilote([bloc({"action": "plan", "steps": ["[ ] a"]}, {"action": "ask", "question": "?"})])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "fais un serveur")
    # Agent First redémarre : nouveau service, même historique.
    nouveau = service_sur(file, historique)
    app = creer_app(file, historique, 2.0, lambda: True, PAR_DEFAUT, cowork=nouveau)
    lancer_tache(TestClient(app), nouveau, conv.id, "8080")
    assert "USER ANSWER TO YOUR QUESTION:" in pilote.textes[1]
    assert "NOT FINISHED: unchecked plan steps: a" in pilote.textes[2]
    file.arreter()


def test_resultats_d_avant_la_question_renvoyes(tmp_path):
    (tmp_path / "a.txt").write_text("contenu", encoding="utf-8")
    pilote = FauxPilote([bloc({"action": "read", "path": "a.txt"}, {"action": "ask", "question": "?"})])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "lis a.txt")
    lancer_tache(client, service, conv.id, "oui")
    assert pilote.textes[1].startswith("RESULTS\n[1] read a.txt: OK\ncontenu")
    file.arreter()


def test_409_si_tache_en_cours(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"})])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    collectes = []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime"})
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, collectes))
    fil.start()
    attendre(collectes, "demande")
    assert service.en_cours(conv.id)
    r = client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "encore"})
    assert r.status_code == 409
    client.post(f"/api/cowork/{conv.id}/arreter")
    fil.join(timeout=5)
    assert not service.en_cours(conv.id)
    file.arreter()


def test_message_refuse_pas_enregistre(tmp_path):
    # Deux envois presque simultanés : le second passe le contrôle « en cours » avant que le
    # premier ait réservé la conversation, puis est refusé. Son texte ne doit pas rester.
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"})])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    collectes = []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime"})
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, collectes))
    fil.start()
    attendre(collectes, "demande")
    service.en_cours = lambda _identifiant: False  # la course : le contrôle passe, la réservation échoue
    try:
        assert client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "encore"}).status_code == 409
        assert [m.texte for m in historique.messages(conv.id) if m.role == "toi"] == ["supprime"]
    finally:
        service.arreter(conv.id)
        fil.join(timeout=5)
        file.arreter()


def test_conversation_renvoie_tache_en_cours(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"})])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    collectes = []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime"})
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, collectes))
    fil.start()
    attendre(collectes, "demande")
    lue = client.get(f"/api/conversations/{conv.id}").json()
    etapes = [m for m in lue["messages"] if m["role"] == "cowork"]
    assert lue["tache"]["en_cours"] is True and lue["tache"]["depuis"] >= len(etapes) > 0
    client.post(f"/api/cowork/{conv.id}/arreter")
    fil.join(timeout=5)
    assert client.get(f"/api/conversations/{conv.id}").json()["tache"]["en_cours"] is False
    file.arreter()


def test_processus_survit_a_la_tache_et_s_arrete(tmp_path):
    reponses = [bloc({"action": "start", "command": "python serveur.py"}), FINI]
    client, file, historique, service = monter(tmp_path, reponses)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    evs = lancer_tache(client, service, conv.id, "lance le serveur")
    assert fin(evs)["type"] == "termine" and fin(evs)["bilan"]["processus"][0]["id"] == 1
    liste = client.get(f"/api/cowork/{conv.id}/processus").json()["processus"]
    assert liste[0]["actif"] is True
    r = client.post(f"/api/cowork/{conv.id}/processus/1/arreter").json()
    assert r["ok"] is True
    assert client.get(f"/api/cowork/{conv.id}/processus").json()["processus"][0]["actif"] is False
    service.arreter_tout()
    file.arreter()


def test_arreter_tout_arrete_d_abord_la_tache(tmp_path):
    # À la fermeture d'Agent First, une tâche qui attendait encore Gemini ne doit pas
    # lancer un serveur une fois les processus arrêtés : il survivrait à Agent First.
    appele, libere = threading.Event(), threading.Event()

    class PiloteLent(FauxPilote):
        def envoyer(self, *args, **kwargs):
            appele.set()
            libere.wait(5)
            return super().envoyer(*args, **kwargs)

    pilote = PiloteLent([bloc({"action": "start", "command": "python serveur.py"}), FINI])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "lance le serveur"})
    assert appele.wait(5)
    service.arreter_tout()
    libere.set()
    evs = evenements(service, conv.id)
    try:
        assert fin(evs)["type"] == "arret" and fin(evs)["raison"] == "Agent First s'est arrêté"
        assert not [p for p in service.processus(conv.id) if p["actif"]]
    finally:
        service.arreter_tout()
        file.arreter()


def test_processus_dans_le_cadre_suivant(tmp_path):
    pilote = FauxPilote([bloc({"action": "start", "command": "python serveur.py"}), FINI, FINI])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "lance")
    lancer_tache(client, service, conv.id, "et après")
    assert "RUNNING PROCESSES: #1 python serveur.py" in pilote.textes[-1]
    service.arreter_tout()
    file.arreter()


def test_etat_d_une_tache(tmp_path):
    client, file, historique, service = monter(tmp_path, [bloc({"action": "plan", "steps": ["[x] a"]}), FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "plan")
    etat = service.etat(conv.id)
    assert etat["statut"] == "done" and etat["plan"] == [{"texte": "a", "fait": True}] and etat["resume"] == "fait"
    # après un redémarrage, l'état est relu dans l'historique
    relu = service_sur(file, historique).etat(conv.id)
    assert relu["statut"] == "done" and relu["plan"] == etat["plan"] and relu["bilan"] == etat["bilan"]
    file.arreter()


def test_diffuseur_recoit_la_demande_d_accord(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    diffuseur = Diffuseur()
    abonne = diffuseur.abonner()
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"})], diffuseur=diffuseur)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime"})
    vus = []
    fin = time.monotonic() + 5
    while time.monotonic() < fin and not any(e["type"] == "demande" for e in vus):
        try:
            vus.append(abonne.get(timeout=0.1))
        except Exception:
            pass
    demande = next(e for e in vus if e["type"] == "demande")
    assert demande["conversation_id"] == conv.id and demande["statut"] == "waiting_approval"
    service.arreter(conv.id)
    file.arreter()


def test_toujours_autoriser_vaut_pour_la_conversation(tmp_path):
    for nom in ("a.txt", "b.txt"):
        (tmp_path / nom).write_text("x", encoding="utf-8")
    reponses = [bloc({"action": "delete", "path": "a.txt"}), FINI, bloc({"action": "delete", "path": "b.txt"}), FINI]
    client, file, historique, service = monter(tmp_path, reponses)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    collectes = []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime a"})
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, collectes))
    fil.start()
    demande = attendre(collectes, "demande")
    client.post(f"/api/cowork/{conv.id}/decision",
                json={"etape": demande["etape"], "reponse": "continuer", "toujours": True})
    fil.join(timeout=5)
    # 2e tâche dans la même conversation : la suppression passe sans demander
    seconde = lancer_tache(client, service, conv.id, "supprime b")
    assert "demande" not in types(seconde)
    assert "autorise" in types(seconde)  # l'utilisateur voit quand même passer l'action
    assert not (tmp_path / "b.txt").exists()
    file.arreter()


def test_accord_sans_reponse_arrete_la_tache(tmp_path):
    # Sans limite, une demande restée sans réponse bloquerait toute la file de Gemini (Chat compris).
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"}), FINI], delai_accord=0.2)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    evs = lancer_tache(client, service, conv.id, "supprime a.txt")
    assert "refus" in types(evs) and types(evs)[-1] == "arret"
    assert "accord" in fin(evs)["raison"]
    assert (tmp_path / "a.txt").exists()
    file.arreter()


def test_cowork_laisse_a_gemini_sa_propre_limite_par_message(tmp_path):
    # 4 Argon peut réfléchir plusieurs minutes avant d'écrire : la limite du Chat (180 s) est trop courte.
    pilote = FauxPilote([FINI])
    client, file, historique, service = monter(tmp_path, [], pilote=pilote, delai_reponse=600.0)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "rien")
    assert pilote.delais == [600.0]
    file.arreter()


def test_arreter_coupe_un_lot(tmp_path):
    lances = []

    def lent(texte, dossier, delai, arret=None):
        lances.append(texte)
        time.sleep(0.3)
        return 0, "ok"

    pilote = FauxPilote([bloc(*[{"action": "run", "command": f"echo {i}"} for i in range(5)])])
    file = FileAttente(lambda: pilote)
    file.demarrer()
    historique = Historique(tmp_path / "historique.db")
    service = ServiceCowork(file, historique, lambda d, p, a: Executeur(d, 5, 8000, lancer=lent, processus=p, arret=a),
                            REGLAGES, fabrique_processus)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    service.demarrer(conv.id, str(tmp_path), None, "cinq commandes", None, None)
    while not lances:
        time.sleep(0.02)
    service.arreter(conv.id)
    evs = evenements(service, conv.id)
    assert len(lances) < 5 and fin(evs)["type"] == "arret"
    file.arreter()


def test_decision_sur_la_mauvaise_etape_refusee(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"}), FINI])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    collectes = []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime"})
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, collectes))
    fil.start()
    demande = attendre(collectes, "demande")
    r = client.post(f"/api/cowork/{conv.id}/decision", json={"etape": demande["etape"] + 7, "reponse": "continuer"})
    assert r.status_code == 409 and (tmp_path / "a.txt").exists()
    assert client.post(f"/api/cowork/{conv.id}/decision", json={"etape": demande["etape"], "reponse": "continuer"}).status_code == 200
    fil.join(timeout=5)
    assert not (tmp_path / "a.txt").exists()
    file.arreter()


def test_decision_tres_rapide_pas_perdue(tmp_path):
    # Un programme qui répond dès qu'il voit « demande » ne doit pas voir son accord effacé.
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"}), FINI], delai_accord=3)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    vus = []

    def repondre_aussitot():
        for ligne in service.flux(conv.id):
            if ligne.startswith("data:"):
                ev = json.loads(ligne[5:])
                vus.append(ev)
                if ev["type"] == "demande":
                    service.decider(conv.id, ev["etape"], "continuer", False)

    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime"})
    fil = threading.Thread(target=repondre_aussitot)
    fil.start()
    fil.join(timeout=10)
    assert fin(vus)["type"] == "termine" and not (tmp_path / "a.txt").exists()
    file.arreter()


def test_processus_publie_avec_sa_liste(tmp_path):
    diffuseur = Diffuseur()
    abonne = diffuseur.abonner()
    client, file, historique, service = monter(tmp_path, [bloc({"action": "start", "command": "python s.py"}), FINI],
                                               diffuseur=diffuseur)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    lancer_tache(client, service, conv.id, "lance")
    publies = []
    while not abonne.empty():
        publies.append(abonne.get())
    processus = [e for e in publies if e["type"] == "processus"]
    assert processus and all(isinstance(e.get("liste"), list) for e in processus)
    service.arreter_tout()
    file.arreter()


def test_etats_en_cours_pour_le_flux_global(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client, file, historique, service = monter(tmp_path, [bloc({"action": "delete", "path": "a.txt"})])
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    collectes = []
    client.post(f"/api/cowork/{conv.id}/messages", json={"texte": "supprime"})
    fil = threading.Thread(target=drainer_dans, args=(service, conv.id, collectes))
    fil.start()
    attendre(collectes, "demande")
    assert {"conversation_id": conv.id, "type": "statut", "statut": "waiting_approval"}.items() <= service.etats_en_cours()[0].items()
    service.arreter(conv.id)
    fil.join(timeout=5)
    assert service.etats_en_cours() == []
    file.arreter()


def test_preparation_impossible_ne_bloque_pas_la_conversation(tmp_path):
    def casse(*_):
        raise RuntimeError("dossier illisible")

    pilote = FauxPilote([FINI])
    file = FileAttente(lambda: pilote)
    file.demarrer()
    historique = Historique(tmp_path / "historique.db")
    service = ServiceCowork(file, historique, casse, REGLAGES, fabrique_processus)
    conv = historique.creer(mode="cowork", dossier=str(tmp_path))
    service.demarrer(conv.id, str(tmp_path), None, "x", None, None)
    evs = evenements(service, conv.id)
    assert fin(evs)["type"] == "erreur" and "dossier illisible" in fin(evs)["corps"]
    assert not service.en_cours(conv.id)
    file.arreter()
