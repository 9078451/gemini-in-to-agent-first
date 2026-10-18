from agent_first.mediatheque import Mediatheque, mime_de
from pilote.modeles import Media

CONVERSATION = "0123456789abcdef0123456789abcdef"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10


def test_enregistrer_puis_retrouver(tmp_path):
    mediatheque = Mediatheque(tmp_path / "medias")
    decrits = mediatheque.enregistrer(CONVERSATION, [Media("image", "image/png", PNG, "un chat"), Media("video", "video/mp4", b"mp4")])
    assert [(d["type"], d["mime"], d["octets"], d["description"]) for d in decrits] == [
        ("image", "image/png", len(PNG), "un chat"), ("video", "video/mp4", 3, ""),
    ]
    assert decrits[0]["id"].startswith(f"{CONVERSATION}/") and decrits[0]["id"].endswith(".png")
    chemin = mediatheque.chemin(decrits[0]["id"])
    assert chemin.read_bytes() == PNG and mime_de(chemin) == "image/png"
    assert mime_de(mediatheque.chemin(decrits[1]["id"])) == "video/mp4"
    assert not list((tmp_path / "medias" / CONVERSATION).glob("*.part"))


def test_identifiants_mal_formes_refuses(tmp_path):
    mediatheque = Mediatheque(tmp_path / "medias")
    (tmp_path / "secret.txt").write_text("x")
    for identifiant in ("../secret.txt", f"{CONVERSATION}/../../secret.txt", f"{CONVERSATION}/0123456789ab.png", "x/y", ""):
        assert mediatheque.chemin(identifiant) is None


def test_supprimer_retire_les_fichiers(tmp_path):
    mediatheque = Mediatheque(tmp_path / "medias")
    identifiant = mediatheque.enregistrer(CONVERSATION, [Media("image", "image/png", PNG)])[0]["id"]
    mediatheque.supprimer(CONVERSATION)
    assert mediatheque.chemin(identifiant) is None
    mediatheque.supprimer("../..")  # ignoré
    assert tmp_path.exists()
