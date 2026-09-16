"""Text piesne, ktory sa nenasiel, sa po case hlada znova.

Metal Archives dopina texty az dni po vydani albumu. Znacka `__NO_LYRICS__`
kedysi platila navzdy, takze prehravac pri Nunslaughteri (9/2026) ukazoval
"Texty piesni sa nenasli", hoci na MA uz boli — a pomohlo len rucne mazanie
priecinka `.lyrics`. Tieto testy drzia, ze:

  1. cerstva znacka sa nehlada znova (MA sa nezahlti),
  2. den stara znacka pri novom albume sa hlada znova,
  3. pri znacke starej mesiace sa hlada az po 30 dnoch,
  4. prazdny vysledok sa nedrzi v pamati do konca behu,
  5. pred opatovnym hladanim sa zabudne album v pamati MA,
  6. subor so znackou ma stale presne `__NO_LYRICS__` (starsia verzia na
     druhom notebooku ho inak zobrazi ako text).

Siet sa nedotyka — Metal Archives je podvrhnuty.
"""

from __future__ import annotations

import os
import time

import pytest

from music_player import disk_cache, metal_archives as ma, web_metadata

DEN = 86400


@pytest.fixture(autouse=True)
def cista_pamat():
    web_metadata._lyrics_cache.clear()
    yield
    web_metadata._lyrics_cache.clear()


@pytest.fixture
def skladba(tmp_path):
    mp3 = tmp_path / "Nunslaughter - Satanic Chaos Legions (2026)" / "01 - Heavenless.mp3"
    mp3.parent.mkdir()
    mp3.write_bytes(b"")
    return str(mp3)


@pytest.fixture
def ma_odpoved(monkeypatch):
    """Podvrhnuty MA: vrati to, co je prave v zozname, a zapisuje dopyty."""
    stav = {"text": "", "dopyty": 0, "zabudnute": []}

    def hladaj(artist, title, album):
        stav["dopyty"] += 1
        return stav["text"]

    monkeypatch.setattr(web_metadata, "_lyrics_from_metal_archives", hladaj)
    monkeypatch.setattr(ma, "zabudni_album", lambda a, b: stav["zabudnute"].append((a, b)))
    return stav


def zostarni(skladba: str, dni: float) -> None:
    """Posun posledny zapis znacky do minulosti."""
    subor = disk_cache._lyrics_path(skladba, "Heavenless")
    t = time.time() - dni * DEN
    os.utime(subor, (t, t))


def nacitaj(skladba: str) -> str:
    return web_metadata.fetch_lyrics("Nunslaughter", "Heavenless", "Satanic Chaos Legions", skladba)


# ── pravidlo ─────────────────────────────────────────────────────────────────


def test_novy_album_sa_skusa_znova_po_dni():
    teraz = 1_000 * DEN
    prve = teraz - 3 * DEN
    assert not disk_cache.treba_znova_hladat(prve, teraz - 0.5 * DEN, teraz)
    assert disk_cache.treba_znova_hladat(prve, teraz - 1 * DEN, teraz)


def test_stara_znacka_sa_skusa_raz_za_mesiac():
    teraz = 1_000 * DEN
    prve = teraz - 200 * DEN
    assert not disk_cache.treba_znova_hladat(prve, teraz - 10 * DEN, teraz)
    assert disk_cache.treba_znova_hladat(prve, teraz - 30 * DEN, teraz)


# ── cela cesta ───────────────────────────────────────────────────────────────


def test_cerstva_znacka_sa_nehlada_znova(skladba, ma_odpoved):
    assert nacitaj(skladba) == ""
    assert nacitaj(skladba) == ""
    assert ma_odpoved["dopyty"] == 1


def test_doplneny_text_sa_najde_na_druhy_den(skladba, ma_odpoved):
    """Presne pripad Nunslaughter: najprv nic, o den neskor text na MA je."""
    assert nacitaj(skladba) == ""
    ma_odpoved["text"] = "Heavenless skies..."
    zostarni(skladba, 1.1)

    assert nacitaj(skladba) == "Heavenless skies..."
    assert ma_odpoved["zabudnute"] == [("Nunslaughter", "Satanic Chaos Legions")]
    assert disk_cache.read_cached_lyrics(skladba, "Heavenless") == "Heavenless skies..."


def test_prazdny_vysledok_nie_je_v_pamati(skladba, ma_odpoved):
    """Prehravac bezi dni — "nenaslo sa" v pamati by zostarnutie znacky obislo."""
    nacitaj(skladba)
    assert web_metadata._key("Nunslaughter", "Heavenless") not in web_metadata._lyrics_cache


def test_opakovane_nenaslo_posunie_dalsie_hladanie(skladba, ma_odpoved):
    nacitaj(skladba)
    zostarni(skladba, 2)
    nacitaj(skladba)
    assert ma_odpoved["dopyty"] == 2
    nacitaj(skladba)
    assert ma_odpoved["dopyty"] == 2


def test_znacka_ostava_citatelna_pre_starsiu_verziu(skladba, ma_odpoved):
    nacitaj(skladba)
    zostarni(skladba, 2)
    nacitaj(skladba)
    obsah = disk_cache._lyrics_path(skladba, "Heavenless").read_text(encoding="utf-8")
    assert obsah == "__NO_LYRICS__"


def test_zabudni_album_zahodi_prazdny_album():
    kluc = ma._key("Nunslaughter", "Satanic Chaos Legions")
    ma._album_cache[kluc] = 1414555
    ma._tracks_cache[1414555] = []
    ma._band_albums_cache["nunslaughter"] = []
    try:
        ma.zabudni_album("Nunslaughter", "Satanic Chaos Legions")
        assert kluc not in ma._album_cache
        assert 1414555 not in ma._tracks_cache
        assert "nunslaughter" not in ma._band_albums_cache
    finally:
        ma._album_cache.pop(kluc, None)
        ma._tracks_cache.pop(1414555, None)
        ma._band_albums_cache.pop("nunslaughter", None)
