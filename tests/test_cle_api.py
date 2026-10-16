from agent_first.cle_api import GardeCle, lire_ou_creer_cle


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_cle_creee_une_fois(tmp_path):
    fichier = tmp_path / "donnees" / "cle_api.txt"
    cle = lire_ou_creer_cle(fichier)
    assert len(cle) >= 40 and fichier.read_text(encoding="utf-8").strip() == cle
    assert lire_ou_creer_cle(fichier) == cle


def test_verifier(tmp_path):
    garde = GardeCle(tmp_path / "cle.txt")
    assert garde.verifier("1.2.3.4", f"Bearer {garde.cle}") is None
    assert garde.verifier("1.2.3.4", f"bearer {garde.cle}") is None
    assert garde.verifier("1.2.3.4", None) == 401
    assert garde.verifier("1.2.3.4", "Bearer mauvaise") == 401
    assert garde.verifier("1.2.3.4", garde.cle) == 401  # sans « Bearer »


def test_trop_d_essais_bloque_puis_debloque(tmp_path):
    horloge = Horloge()
    garde = GardeCle(tmp_path / "cle.txt", essais_max=10, fenetre=60, blocage=60, horloge=horloge)
    for _ in range(10):
        assert garde.verifier("1.2.3.4", "Bearer non") == 401
    assert garde.verifier("1.2.3.4", f"Bearer {garde.cle}") == 429
    assert garde.verifier("5.6.7.8", f"Bearer {garde.cle}") is None  # les autres adresses passent
    horloge.t += 61
    assert garde.verifier("1.2.3.4", f"Bearer {garde.cle}") is None


def test_essais_anciens_oublies(tmp_path):
    horloge = Horloge()
    garde = GardeCle(tmp_path / "cle.txt", essais_max=3, fenetre=60, blocage=60, horloge=horloge)
    garde.verifier("1.2.3.4", "Bearer non")
    garde.verifier("1.2.3.4", "Bearer non")
    horloge.t += 61
    garde.verifier("1.2.3.4", "Bearer non")
    assert garde.verifier("1.2.3.4", f"Bearer {garde.cle}") is None


def test_regenerer(tmp_path):
    fichier = tmp_path / "cle.txt"
    garde = GardeCle(fichier)
    ancienne = garde.cle
    nouvelle = garde.regenerer()
    assert nouvelle != ancienne and fichier.read_text(encoding="utf-8").strip() == nouvelle
    assert garde.verifier("1.2.3.4", f"Bearer {ancienne}") == 401
    assert garde.verifier("1.2.3.4", f"Bearer {nouvelle}") is None
