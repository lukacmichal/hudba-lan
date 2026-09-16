"""Testy pre zoznam metalovych noviniek z NAS-u."""

from __future__ import annotations

import json

import pytest

from music_player import novinky


@pytest.fixture(autouse=True)
def lokalna_kopia(tmp_path, monkeypatch):
    """Kopie a fronta patria do tmp, nie do %APPDATA% skutocneho pouzivatela."""
    monkeypatch.setattr(novinky, "_app_state_dir", lambda: tmp_path / "appdata")
    return tmp_path / "appdata"


def zoznam_na_disk(priecinok, albumy, format_=1, zalozky=None):
    priecinok.mkdir(parents=True, exist_ok=True)
    data = {"format": format_, "albumy": albumy}
    if zalozky is not None:
        data["zalozky"] = zalozky
    (priecinok / novinky.SUBOR).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return priecinok


def a(kluc, **extra):
    zaznam = {"kluc": kluc, "kapela": kluc.split("|")[0], "album": kluc.split("|")[-1]}
    zaznam.update(extra)
    return zaznam


# ── log odskrtnutych ──────────────────────────────────────────────────────────
def test_rozober_log_plati_posledny_riadok():
    """Odklik vedla sa musi dat vratit — preto posledny zapis o albume plati."""
    text = "\n".join([
        novinky.riadok_logu("vader|de profundis", True),
        novinky.riadok_logu("behemoth|satanica", True),
        novinky.riadok_logu("vader|de profundis", False),
    ])
    assert novinky.rozober_log(text) == {"behemoth|satanica"}


def test_rozober_log_preskoci_polovicny_riadok():
    """Dva stroje zapisali naraz: album ostane neprecitany, zvysok plati."""
    text = ('{"kluc": "vader|de pro\n'
            + novinky.riadok_logu("behemoth|satanica") + "\n")
    assert novinky.rozober_log(text) == {"behemoth|satanica"}


def test_riadok_logu_je_jeden_riadok():
    riadok = novinky.riadok_logu("kapela|album s | rurou")
    assert "\n" not in riadok
    assert json.loads(riadok)["kluc"] == "kapela|album s | rurou"


# ── obsah zoznamu ─────────────────────────────────────────────────────────────
def test_rozober_zoznam_odmietne_novsi_format():
    """Zoznamu, ktoremu nemozem rozumiet, sa radsej netvarim, ze rozumiem."""
    text = json.dumps({"format": novinky.FORMAT + 1, "albumy": [a("x|y")]})
    assert novinky.rozober_zoznam(text) == []


def test_rozober_zoznam_znesie_smeti():
    assert novinky.rozober_zoznam("nie je JSON") == []
    assert novinky.rozober_zoznam(json.dumps({"albumy": [{"bez": "kluca"}]})) == []


def test_album_popis_a_odkazy():
    album = novinky.Album(kluc="k|a", kapela="Avulsed", album="Nordic", krajina="Spain",
                          typ="Full-length", styl="Death Metal", vydane="September 9th, 2026",
                          pribudlo="2026-09-04")
    assert album.nadpis == "Avulsed (Spain) — Nordic  [Full-length]"
    assert "Death Metal" in album.popis and "v zozname od 4. 9. 2026" in album.popis
    # Nezaradene polozky odkaz zo skenu nemaju, a prave pri nich je vypocutie
    # to jedine, podla coho sa da rozhodnut.
    assert album.youtube_odkaz.startswith("https://www.youtube.com/results?search_query=")


def test_album_pod_ciarou_ukaze_dovod():
    album = novinky.Album(kluc="k|a", kapela="Tulip", album="The Fall",
                          kategoria="nezaradene", dovod="styl nesedi ani na jeden zoznam")
    assert album.nezaradeny
    assert "styl nesedi" in album.popis


# ── nacitanie ─────────────────────────────────────────────────────────────────
def test_nacitaj_nechava_poradie_zo_suboru(tmp_path):
    # Poradie urcuje sken (podla dna vydania, potom podla abecedy) — on jediny
    # pozna presne datumy. Prehravac ho uz neprehadzuje; do 6. 9. 2026 radil
    # podla toho, kedy album pribudol do zoznamu, a to bolo poradie objavovania.
    nas = zoznam_na_disk(tmp_path / "nas", [
        a("morbid|c", pribudlo="2026-08-01"),
        a("aara|a", pribudlo="2026-09-04"),
        a("zyklon|b", pribudlo="2026-08-15"),
    ])
    z = novinky.nacitaj(nas)
    assert [x.kluc for x in z.albumy] == ["morbid|c", "aara|a", "zyklon|b"]
    assert z.z_nasu and z.pocet_novych == 3


def test_nacitaj_vyhodi_precitane_z_poctu(tmp_path):
    nas = zoznam_na_disk(tmp_path / "nas", [a("a|1"), a("b|2")])
    novinky.oznac(["a|1"], p=nas)
    z = novinky.nacitaj(nas)
    assert z.pocet_novych == 1
    assert [x.kluc for x in z.nove()] == ["b|2"]
    # Zo zoznamu sa NEMAZE — zaskrtavadlo "aj skontrolovane" ho musi vratit.
    assert len(z.albumy) == 2


def test_nedostupny_nas_pouzije_poslednu_kopiu(tmp_path):
    nas = zoznam_na_disk(tmp_path / "nas", [a("a|1")])
    assert novinky.nacitaj(nas).z_nasu is True          # kopia sa odlozi

    z = novinky.nacitaj(tmp_path / "nas-je-prec")
    assert z.z_nasu is False
    assert [x.kluc for x in z.albumy] == ["a|1"]


def test_bez_nasu_a_bez_kopie_je_zoznam_prazdny(tmp_path):
    z = novinky.nacitaj(tmp_path / "nikde")
    assert z.albumy == [] and z.z_nasu is False


# ── odskrtavanie ──────────────────────────────────────────────────────────────
def test_oznacenie_bez_nasu_pocka_a_odide_neskor(tmp_path):
    nas = zoznam_na_disk(tmp_path / "nas", [a("a|1"), a("b|2")])
    novinky.nacitaj(nas)                                # nech je kopia

    # NAS prec: odskrtnutie sa nesmie stratit, len pocka
    assert novinky.oznac(["a|1"], p=tmp_path / "nas-je-prec") is False
    z = novinky.nacitaj(tmp_path / "nas-je-prec")
    assert z.pocet_novych == 1 and z.caka == 1

    # NAS spat: fronta odide sama pri najblizsom nacitani
    z = novinky.nacitaj(nas)
    assert z.caka == 0
    assert novinky.rozober_log((nas / novinky.LOG).read_text(encoding="utf-8")) == {"a|1"}


def test_oznacenie_sa_da_vratit(tmp_path):
    nas = zoznam_na_disk(tmp_path / "nas", [a("a|1")])
    novinky.oznac(["a|1"], p=nas)
    assert novinky.nacitaj(nas).pocet_novych == 0
    novinky.oznac(["a|1"], precitane=False, p=nas)
    assert novinky.nacitaj(nas).pocet_novych == 1


def test_oznacenie_prazdneho_zoznamu_nic_nezapise(tmp_path):
    nas = zoznam_na_disk(tmp_path / "nas", [a("a|1")])
    assert novinky.oznac([], p=nas) is True
    assert not (nas / novinky.LOG).exists()


# ── konfiguracia ──────────────────────────────────────────────────────────────
def test_priecinok_z_konfiguracie(monkeypatch):
    monkeypatch.setattr("music_player.config_loader.load_config",
                        lambda: {"NOVINKY_PRIECINOK": r"D:\novinky"})
    assert str(novinky.priecinok()) == r"D:\novinky"


def test_da_sa_vypnut(monkeypatch):
    monkeypatch.setattr("music_player.config_loader.load_config", lambda: {"NOVINKY": "nie"})
    assert novinky.zapnute() is False
    monkeypatch.setattr("music_player.config_loader.load_config", lambda: {})
    assert novinky.zapnute() is True


# ── zalozky ───────────────────────────────────────────────────────────────────
def test_zalozky_rozdelia_zoznam(tmp_path):
    nas = zoznam_na_disk(
        tmp_path / "nas",
        [a("behemoth|i", vydanie="2026-09-04"), a("nostos|s", vydanie="2026-08-20")],
        zalozky={"tyzden": ["behemoth|i"], "uz_vydane": ["nostos|s"]})

    z = novinky.nacitaj(nas)

    assert [x.kapela for x in z.pre_zalozku("tyzden")] == ["behemoth"]
    assert [x.kapela for x in z.pre_zalozku("uz_vydane")] == ["nostos"]


def test_zalozka_drzi_poradie_zo_suboru(tmp_path):
    nas = zoznam_na_disk(
        tmp_path / "nas",
        [a("morbid|c"), a("aara|a"), a("zyklon|b")],
        zalozky={"tyzden": ["morbid|c", "aara|a", "zyklon|b"]})

    z = novinky.nacitaj(nas)

    assert [x.kluc for x in z.pre_zalozku("tyzden")] == ["morbid|c", "aara|a", "zyklon|b"]


def test_subor_bez_zalaziek_nie_je_chyba(tmp_path):
    # Starsi sken zalozky nepisal a prehravac na taky subor nesmie doplatit —
    # zoznam je vtedy jeden.
    nas = zoznam_na_disk(tmp_path / "nas", [a("a|1")])

    z = novinky.nacitaj(nas)

    assert z.zalozky == {}
    assert z.pre_zalozku("tyzden") == []
    assert len(z.albumy) == 1


def test_zalozka_ignoruje_neznamy_kluc(tmp_path):
    # Kluc, ktory v `albumy` nie je, sa preskoci — nie je z coho spravit riadok.
    nas = zoznam_na_disk(tmp_path / "nas", [a("a|1")],
                         zalozky={"tyzden": ["a|1", "chyba|to"]})

    assert [x.kluc for x in novinky.nacitaj(nas).pre_zalozku("tyzden")] == ["a|1"]


def test_den_vydania_je_z_iso_datumu():
    album = novinky.Album(kluc="k|a", vydanie="2026-09-04", vydane="September 4th, 2026")
    assert album.den == "4. 9. 2026"


def test_den_je_prazdny_ked_datum_nie_je():
    assert novinky.Album(kluc="k|a").den == ""


def test_datum_je_pri_kazdom_albume():
    # Pri rolovani dlhym zoznamom odide nadpis dna hore a bez datumu v riadku
    # sa neda povedat, na co sa clovek pozera.
    album = novinky.Album(kluc="k|a", styl="Black Metal", vydanie="2026-09-04",
                          vydane="4. 9. 2026")
    assert "4. 9. 2026" in album.popis
    assert album.popis.startswith("Black Metal")


def test_mesacne_vydanie_ukaze_mesiac():
    # Ked MA pozna len mesiac, je tam mesiac — predstierat den by znamenalo
    # tvrdit nieco, co o vydani nikto nevie.
    album = novinky.Album(kluc="k|a", styl="Black Metal", vydane="august 2026")
    assert "august 2026" in album.popis
