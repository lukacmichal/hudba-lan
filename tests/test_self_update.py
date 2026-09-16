"""Testy aktualizacie z NAS-u.

Kontroluju to, co sa da pokazit ticho: neplatny manifest, poskodeny balik
a prepisanie osobnych suborov. Sietovy disk sa nahradza obycajnym priecinkom
— appka na nom robi to iste.

Standalone (bez pytestu):
    python tests/test_self_update.py
"""
import hashlib
import json
import shutil
import socket
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_player import self_update as su  # noqa: E402

LOMKA = chr(92)
UNC_KOREN = LOMKA * 2 + "127.0.0.1" + LOMKA


def _manifest_json(**zmeny) -> str:
    data = {
        "versionCode": 14,
        "versionName": "1.4",
        "zip": "metalmusic-pc-1.4.zip",
        "sha256": "a" * 64,
        "notes": "nieco nove",
        "date": "2026-09-02",
    }
    data.update(zmeny)
    return json.dumps(data)


def _urob_zip(cesta: Path, subory: dict[str, str]) -> str:
    cesta.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cesta, "w") as zf:
        for meno, obsah in subory.items():
            zf.writestr(meno, obsah)
    return hashlib.sha256(cesta.read_bytes()).hexdigest()


def _pripravena_verzia(nas: Path, subory: dict[str, str], *, kod: int = 14) -> su.Manifest:
    """Polozi na 'NAS' balik aj manifest a vrati manifest, ako ho vidi appka."""
    meno = f"metalmusic-pc-{kod}.zip"
    sha = _urob_zip(nas / meno, subory)
    (nas / su.MANIFEST).write_text(
        _manifest_json(versionCode=kod, versionName=str(kod), zip=meno, sha256=sha),
        encoding="utf-8",
    )
    m = su.zisti(nas)
    assert m is not None
    return m


# -- manifest -----------------------------------------------------------------
def test_manifest_sa_precita():
    m = su.nacitaj_manifest(_manifest_json())
    assert m is not None
    assert m.kod == 14
    assert m.popis == "1.4 (14)"
    assert m.poznamka == "nieco nove"


def test_manifest_s_bom_sa_precita(tmp_path):
    # PowerShell 5.1 pri `Set-Content -Encoding utf8` prida BOM. Presne na tom
    # sa 31. 8. 2026 zaseklo vydanie androidoveho playera — telefon mlcky
    # tvrdil, ze nova verzia nie je. Tu to zhltneme.
    (tmp_path / su.MANIFEST).write_text(_manifest_json(), encoding="utf-8-sig")
    assert su.zisti(tmp_path) is not None


def test_nezmyselny_manifest_je_none():
    assert su.nacitaj_manifest("toto nie je json") is None
    assert su.nacitaj_manifest("[]") is None
    assert su.nacitaj_manifest(_manifest_json(versionCode="x")) is None
    assert su.nacitaj_manifest(_manifest_json(sha256="krátky")) is None
    assert su.nacitaj_manifest(_manifest_json(zip="")) is None
    # Meno suboru sa sklada s cestou k NAS-u, takze von z priecinka nesmie.
    assert su.nacitaj_manifest(_manifest_json(zip=r"..\Player\metalmusic-2.5.apk")) is None


def test_nedostupny_nas_je_ticho(tmp_path):
    assert su.zisti(tmp_path / "toto-tam-nie-je") is None


def test_share_sa_vytiahne_z_cesty():
    # `net use` sa prihlasuje na share, nie na podpriecinok.
    assert su._share(Path(r"\\nas.local\Android\PlayerPC")) == r"\\nas.local\Android"
    assert su._share(Path(r"\\nas.local\Android")) == r"\\nas.local\Android"
    # Lokalna cesta (a testy) sa neprihlasuju nikam.
    assert su._share(Path(r"C:\NAS\hudba-lan")) == ""


def test_poverenia_sa_precitaju(tmp_path, monkeypatch=None):
    subor = tmp_path / "nas-credentials.local"
    subor.write_text(
        "# komentar\nNAS_HOST=nas.local\nNAS_USER=nasuser\nNAS_PASS=tajne heslo\n",
        encoding="utf-8",
    )
    povodne = su.SUBORY_S_POVERENIAMI
    su.SUBORY_S_POVERENIAMI = (subor,)
    try:
        assert su._poverenia() == ("nasuser", "tajne heslo")
    finally:
        su.SUBORY_S_POVERENIAMI = povodne


def test_bez_poverenii_sa_nikam_neprihlasuje(tmp_path):
    povodne = su.SUBORY_S_POVERENIAMI
    su.SUBORY_S_POVERENIAMI = (tmp_path / "niet",)
    try:
        assert su._poverenia() is None
        assert not su.zabezpec_pristup(tmp_path / "neexistujuci-priecinok")
    finally:
        su.SUBORY_S_POVERENIAMI = povodne


def test_novsia_verzia_sa_pozna():
    m = su.nacitaj_manifest(_manifest_json(versionCode=14))
    assert su.je_novsia(m, lokalny_kod=13)
    assert not su.je_novsia(m, lokalny_kod=14)
    assert not su.je_novsia(m, lokalny_kod=15)


# -- stiahnutie a priprava ----------------------------------------------------
def test_priprava_rozbali_balik(tmp_path):
    nas, ciel = tmp_path / "nas", tmp_path / "appka"
    nas.mkdir()
    ciel.mkdir()
    m = _pripravena_verzia(nas, {"app.pyw": "novy", "music_player/ui.py": "novy"})

    priprava, ponechane = su.priprav(m, nas, ciel)

    assert (priprava / "app.pyw").read_text() == "novy"
    assert (priprava / "music_player" / "ui.py").exists()
    assert ponechane == []
    shutil.rmtree(priprava.parent, ignore_errors=True)


def test_poskodeny_balik_sa_odmietne(tmp_path):
    nas, ciel = tmp_path / "nas", tmp_path / "appka"
    nas.mkdir()
    ciel.mkdir()
    m = _pripravena_verzia(nas, {"app.pyw": "novy"})
    # Prepiseme balik az PO tom, co manifest vznikol — presne to, co sa stane
    # pri prerusenom kopirovani na NAS.
    (nas / m.zip).write_bytes(b"toto uz nie je ten subor")

    try:
        su.priprav(m, nas, ciel)
    except su.ChybaAktualizacie as exc:
        assert "sucet" in str(exc)
    else:
        raise AssertionError("poskodeny balik presiel")


def test_osobne_subory_sa_neprepisu(tmp_path):
    nas, ciel = tmp_path / "nas", tmp_path / "appka"
    nas.mkdir()
    ciel.mkdir()
    (ciel / "config.txt").write_text("MP3_TARGET=D:\\hudba", encoding="utf-8")
    (ciel / "spanok.m3u").write_text("moje skladby", encoding="utf-8")
    m = _pripravena_verzia(nas, {
        "app.pyw": "novy",
        "config.txt": "MP3_TARGET=C:\\data\\mp3",
        "spanok.m3u": "",
        "spanok2.m3u": "",       # tento v instalacii CHYBA -> vzor sa doplni
    })

    priprava, ponechane = su.priprav(m, nas, ciel)

    assert not (priprava / "config.txt").exists()
    assert not (priprava / "spanok.m3u").exists()
    assert (priprava / "spanok2.m3u").exists()
    assert (priprava / "app.pyw").exists()
    assert ponechane == ["config.txt", "spanok.m3u"]
    shutil.rmtree(priprava.parent, ignore_errors=True)


def test_skratka_a_poverenia_sa_neprepisu(tmp_path):
    nas, ciel = tmp_path / "nas", tmp_path / "appka"
    nas.mkdir()
    ciel.mkdir()
    # .lnk nesie absolutnu cestu k TOMUTO stroju, .local su poverenia.
    (ciel / "Metal Music Player.lnk").write_text("skratka", encoding="utf-8")
    (ciel / "nas-credentials.local").write_text("NAS_PASS=tajne", encoding="utf-8")
    m = _pripravena_verzia(nas, {
        "Metal Music Player.lnk": "z ineho notebooku",
        "nas-credentials.local": "prazdne",
    })

    priprava, ponechane = su.priprav(m, nas, ciel)

    assert ponechane == ["Metal Music Player.lnk", "nas-credentials.local"]
    assert not list(priprava.iterdir())
    shutil.rmtree(priprava.parent, ignore_errors=True)


def test_balik_s_vrchnym_priecinkom(tmp_path):
    # Balik sa robi bez vrchneho priecinka, ale keby ho niekto raz zabalil aj
    # s nim, nesmie z toho vzniknut priecinok v priecinku.
    nas, ciel = tmp_path / "nas", tmp_path / "appka"
    nas.mkdir()
    ciel.mkdir()
    m = _pripravena_verzia(nas, {"hudba-lan/app.pyw": "novy"})

    priprava, _ = su.priprav(m, nas, ciel)

    assert (priprava / "app.pyw").read_text() == "novy"
    shutil.rmtree(priprava.parent, ignore_errors=True)


# ── je NAS na dosah, alebo som mimo domu? ─────────────────────────────────────
# Toto je rozdiel, ktory appka do 6. 9. 2026 nerozlisovala, a preto o pokazenych
# aktualizaciach mlcala. Testuje sa cez pravy soket na 127.0.0.1; port sa
# docasne prepise, aby test nepotreboval prava na 445.
def test_server_odpoveda_ked_niekto_pocuva():
    with socket.socket() as pocuvadlo:
        pocuvadlo.bind(("127.0.0.1", 0))
        pocuvadlo.listen(1)
        port = pocuvadlo.getsockname()[1]
        povodny, su.SMB_PORT = su.SMB_PORT, port
        try:
            assert su.server_odpoveda(Path(UNC_KOREN + "share" + LOMKA + "app"))
        finally:
            su.SMB_PORT = povodny


def test_server_neodpoveda_ked_nikto_nepocuva():
    # Port sa otvori a hned zavrie — cislo teda urcite nikto nedrzi.
    with socket.socket() as pomocny:
        pomocny.bind(("127.0.0.1", 0))
        port = pomocny.getsockname()[1]
    povodny, su.SMB_PORT = su.SMB_PORT, port
    try:
        assert not su.server_odpoveda(
            Path(UNC_KOREN + "share" + LOMKA + "app"), sekund=0.5)
    finally:
        su.SMB_PORT = povodny


def test_server_odpoveda_lokalna_cesta_je_nie():
    # Lokalny priecinok nie je share; nema sa na co pytat.
    assert not su.server_odpoveda(Path(tempfile.gettempdir()))


if __name__ == "__main__":
    zlyhania = 0
    for meno, funkcia in sorted(globals().items()):
        if not meno.startswith("test_") or not callable(funkcia):
            continue
        docasny = Path(tempfile.mkdtemp(prefix="test-self-update-"))
        try:
            if funkcia.__code__.co_argcount:
                funkcia(docasny)
            else:
                funkcia()
            print(f"OK   {meno}")
        except Exception as exc:               # noqa: BLE001 - vypis, nie preposlanie
            zlyhania += 1
            print(f"ZLE  {meno}: {exc}")
        finally:
            shutil.rmtree(docasny, ignore_errors=True)
    print("hotovo" if not zlyhania else f"zlyhalo {zlyhania}")
    sys.exit(1 if zlyhania else 0)
