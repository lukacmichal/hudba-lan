"""Testy pre scrapovanie Metal Archives — parsovanie stranky albumu.

Sietove dopyty sa tu nerobia: HTML je v testoch natvrdo, presne v tvare, aky
MA posiela. Overuje sa to, na com to 7. 9. 2026 spadlo — vinylove vydanie ma
v ID skladby stranu platne (`lyricsButton8169012B`).
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from music_player import metal_archives as ma


def stranka(*riadky: str) -> BeautifulSoup:
    """Zabali riadky tabulky do takej kostry, aku ma stranka albumu na MA."""
    return BeautifulSoup(
        '<table class="display table_lyrics"><tbody>' + "".join(riadky) + "</tbody></table>",
        "lxml",
    )


def riadok(track_id: str, nazov: str, cas: str = "03:07") -> str:
    return (
        '<tr class="even">'
        '<td width="20"><a name="' + track_id + '"></a>' + track_id + ".</td>"
        "<td class='wrapWords'>" + nazov + "</td>"
        '<td align="right">' + cas + "</td>"
        '<td nowrap="nowrap"><a href="#" id="lyricsButton' + track_id + '">Show lyrics</a></td>'
        "</tr>"
    )


@pytest.fixture(autouse=True)
def cista_cache():
    """Kazdy test si berie vlastne album_id, ale cache nech nepretecie medzi nimi."""
    ma._tracks_cache.clear()
    ma._band_albums_cache.clear()
    yield
    ma._tracks_cache.clear()
    ma._band_albums_cache.clear()


def test_cd_album_ma_ciselne_id():
    soup = stranka(riadok("7654321", "Hail Satan"))
    assert ma._parse_tracks_from_soup(1, soup) == [("7654321", "Hail Satan")]


def test_vinyl_si_necha_stranu_platne():
    """Strana A/B v ID sa NESMIE orezat — inak album vyzera prazdny.

    Presne toto zakrylo texty k Nunslaughter - Satanic Chaos Legions: 14
    skladieb, vsetky s pismenom na konci ID, a parser vratil nulu.
    """
    soup = stranka(
        riadok("8169005A", "Satanic Chaos Legions"),
        riadok("8169012B", "In the Flames of Inferno"),
    )
    assert ma._parse_tracks_from_soup(2, soup) == [
        ("8169005A", "Satanic Chaos Legions"),
        ("8169012B", "In the Flames of Inferno"),
    ]


def test_najde_skladbu_aj_s_cislom_v_nazve():
    tracks = [("8169013B", "Heavenless")]
    assert ma._find_track_id(tracks, "01 - Heavenless") == "8169013B"
    assert ma._find_track_id(tracks, "Heavenless") == "8169013B"
    assert ma._find_track_id(tracks, "Heavenless (live)") is None


def test_zalozne_hladanie_ma_strop_a_riadne_albumy_ide_prve(monkeypatch):
    """Kapela s 200 vydaniami by inak znamenala 5 minut stahovania na skladbu."""
    vydania = [(i, f"Split {i}", "Split") for i in range(100, 300)]
    vydania.append((7, "Riadny album", "Full-length"))
    vydania.append((8, "Kompilacia", "Compilation"))
    monkeypatch.setattr(ma, "_search_band_albums", lambda _artist: vydania)

    vybrane = ma._zalozne_albumy("Nunslaughter", set())

    assert len(vybrane) == ma._MAX_ZALOZNYCH_ALBUMOV
    assert vybrane[0][0] == 7          # full-length pred splitmi
    assert vybrane[1][0] == 8          # kompilacia pred splitmi


def test_zalozne_hladanie_nesiahne_dvakrat_po_tom_istom_albume(monkeypatch):
    vydania = [(7, "Riadny album", "Full-length"), (8, "Split", "Split")]
    monkeypatch.setattr(ma, "_search_band_albums", lambda _artist: vydania)

    assert [a[0] for a in ma._zalozne_albumy("Nunslaughter", {7})] == [8]
