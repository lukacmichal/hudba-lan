"""Tlacidlo "Nacitat texty" — `fetch_lyrics(..., vynutit=True)`.

  1. obide cerstvu znacku "nenaslo sa" aj pamat a spyta sa MA hned,
  2. zabudne "nenaslo sa" pri ostatnych skladbach albumu (nie ich texty),
  3. dobry text z disku NEPREPISE prazdnym vysledkom (MA prave neodpoveda),
  4. zmeneny text zahodi stary preklad.

Siet sa nedotyka — Metal Archives je podvrhnuty.
"""

from __future__ import annotations

import pytest

from music_player import disk_cache, metal_archives as ma, web_metadata


@pytest.fixture(autouse=True)
def cista_pamat():
    web_metadata._lyrics_cache.clear()
    yield
    web_metadata._lyrics_cache.clear()


@pytest.fixture
def album(tmp_path):
    priecinok = tmp_path / "Nunslaughter - Satanic Chaos Legions (2026)"
    priecinok.mkdir()
    skladby = []
    for meno in ("01 - Heavenless.mp3", "02 - The Spear of Satan.mp3"):
        (priecinok / meno).write_bytes(b"")
        skladby.append(str(priecinok / meno))
    return skladby


@pytest.fixture
def ma_odpoved(monkeypatch):
    stav = {"text": "", "dopyty": 0, "zabudnute": 0}

    def hladaj(artist, title, album_):
        stav["dopyty"] += 1
        return stav["text"]

    def zabudni(a, b):
        stav["zabudnute"] += 1

    monkeypatch.setattr(web_metadata, "_lyrics_from_metal_archives", hladaj)
    monkeypatch.setattr(ma, "zabudni_album", zabudni)
    return stav


def nacitaj(skladba, title="Heavenless", vynutit=False):
    return web_metadata.fetch_lyrics("Nunslaughter", title, "Satanic Chaos Legions",
                                     skladba, vynutit=vynutit)


def test_vynutene_obide_cerstvu_znacku(album, ma_odpoved):
    assert nacitaj(album[0]) == ""
    ma_odpoved["text"] = "Heavenless skies..."

    assert nacitaj(album[0]) == ""                      # znacka je cerstva
    assert nacitaj(album[0], vynutit=True) == "Heavenless skies..."
    assert ma_odpoved["zabudnute"] == 1
    assert disk_cache.read_cached_lyrics(album[0], "Heavenless") == "Heavenless skies..."


def test_vynutene_zabudne_nenaslo_celemu_albumu(album, ma_odpoved):
    nacitaj(album[1], title="The Spear of Satan")        # znacka pri 2. skladbe
    disk_cache.write_cached_lyrics(album[0], "Heavenless", "stary text")
    ma_odpoved["text"] = "novy text"

    nacitaj(album[0], vynutit=True)

    assert disk_cache.read_cached_lyrics(album[1], "The Spear of Satan") is None
    assert disk_cache.read_cached_lyrics(album[0], "Heavenless") == "novy text"


def test_vynutene_neprepise_dobry_text_prazdnym(album, ma_odpoved):
    disk_cache.write_cached_lyrics(album[0], "Heavenless", "dobry text")
    ma_odpoved["text"] = ""

    assert nacitaj(album[0], vynutit=True) == "dobry text"
    assert disk_cache.read_cached_lyrics(album[0], "Heavenless") == "dobry text"


def test_zmeneny_text_zahodi_preklad(album, ma_odpoved):
    disk_cache.write_cached_lyrics(album[0], "Heavenless", "stary text")
    disk_cache.write_cached_translation(album[0], "Heavenless", "stary preklad")
    ma_odpoved["text"] = "opraveny text"

    nacitaj(album[0], vynutit=True)

    assert disk_cache.read_cached_translation(album[0], "Heavenless") is None
