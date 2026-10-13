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


# ── nazov albumu s preklepom (Christ Dismembered, 21. 9. 2026) ────────────────


class _Odpoved:
    def __init__(self, riadky):
        self._riadky = riadky

    def json(self):
        return {"aaData": self._riadky}


def _riadok_hladania(kapely: str, album_id: int, nazov: str, typ: str = "Full-length") -> list[str]:
    kapela_html = " | ".join(f'<a href="https://x/bands/{k}/1" title="{k}">{k}</a>' for k in kapely.split(" | "))
    return [kapela_html, f'<a href="https://x/albums/_/_/{album_id}">{nazov}</a> <!-- 2.3 -->', typ]


DISKOGRAFIA_CD = [
    _riadok_hladania("Christ Dismembered", 1101171, "Archbishop", "Single"),
    _riadok_hladania("Christ Dismembered", 652104, "Christ Dismembered"),
    _riadok_hladania("Christ Dismembered", 477445, "Live Ritual 2014", "Live album"),
    _riadok_hladania("Christ Dismembered", 1295119, "Ov Vampiricy"),
    _riadok_hladania("Towards Global Holocaust | Christ Dismembered", 256050,
                     "Upon Firmaments of Sacrilege and Genocide", "Split"),
]


@pytest.fixture
def ma_bez_siete(monkeypatch):
    """Hladanie podla nazvu nevrati nic, diskografia kapely vrati `DISKOGRAFIA_CD`."""
    ma._album_cache.clear()

    def falosny_get(_url, params=None, **_kw):
        if params and params.get("releaseTitle"):
            return _Odpoved([])
        return _Odpoved(DISKOGRAFIA_CD)

    monkeypatch.setattr(ma, "_get", falosny_get)
    yield
    ma._album_cache.clear()


def test_preklep_v_tagu_najde_album(ma_bez_siete):
    """Tagy maju "Ov Vampiracy", MA aj Bandcamp kapely "Ov Vampiricy"."""
    assert ma.search_album("Christ Dismembered", "Ov Vampiracy") == 1295119


def test_iny_zapis_bez_preklepu_najde_album(ma_bez_siete):
    assert ma.search_album("Christ Dismembered", "OV VAMPIRICY (Remastered)") == 1295119


def test_album_ktory_na_ma_nie_je_ostane_bez_odkazu(ma_bez_siete):
    assert ma.search_album("Christ Dismembered", "Sorcerer Ov Nazareth") is None
    assert ma.search_album("Christ Dismembered", "Live Ritual 2015") is None


def test_cudzia_kapela_s_podobnym_menom_sa_do_diskografie_nepripleti(monkeypatch):
    """MA hlada kapelu podla casti mena — "Dismembered" vrati aj Christ Dismembered."""
    riadky = [
        _riadok_hladania("Dismembered", 11, "Dismembered"),
        _riadok_hladania("Christ Dismembered", 1295119, "Ov Vampiricy"),
        _riadok_hladania("Dismembered Pig | Anal Disfigurement", 12, "Split s prasatom", "Split"),
        _riadok_hladania("Dismembered | Iná kapela", 13, "Spolocny split", "Split"),
    ]
    monkeypatch.setattr(ma, "_get", lambda *_a, **_kw: _Odpoved(riadky))

    assert ma._search_band_albums("Dismembered") == [
        (11, "Dismembered", "Full-length"),
        (13, "Spolocny split", "Split"),
    ]


def test_kapela_s_diakritikou_sa_najde_aj_bez_nej(monkeypatch):
    riadky = [_riadok_hladania("Bo&ouml;tes Void", 21, "Wurmloch")]
    monkeypatch.setattr(ma, "_get", lambda *_a, **_kw: _Odpoved(riadky))

    assert ma._search_band_albums("Boötes Void") == [(21, "Wurmloch", "Full-length")]


@pytest.mark.parametrize(
    ("nase", "ich", "zhoda"),
    [
        ("Ov Vampiracy", "Ov Vampiricy", 1),       # zamenene pismeno
        ("Ov Vampircy", "Ov Vampiricy", 1),        # chybajuce pismeno
        ("Ov Vampiricyy", "Ov Vampiricy", 1),      # pismeno navyse
        ("Ov Vapmiricy", "Ov Vampiricy", 1),       # prehodene pismena
        ("Fools Gambit", "Fool's Gambit", 2),      # apostrof nie je preklep
        ("Death II", "Death III", 0),              # rimske cislo = ine vydanie
        ("Live 2014", "Live 2015", 0),             # cislo = ine vydanie
        ("Hail Satan", "Nail Satan", 0),           # kratke slovo sa netipuje
        ("Ov Vampiracy", "Ov Vampirizzy", 0),      # dve pismena
        ("Mother Ov Demons", "Mother of Demons", 0),
        ("Ov Vampiracy", "Ov Vampiricy Live", 0),  # slovo navyse
    ],
)
def test_co_je_preklep(nase, ich, zhoda):
    assert ma._zhoda_nazvu(ma._slova_nazvu(nase), ma._slova_nazvu(ich)) == zhoda


def test_dva_rovnako_podobne_albumy_sa_netipuju(monkeypatch):
    monkeypatch.setattr(ma, "_search_band_albums", lambda _a: [
        (1, "Ov Vampiricy", "Full-length"),
        (2, "Ov Vampiraca", "EP"),
    ])
    assert ma._album_z_diskografie("Christ Dismembered", "Ov Vampiracy") is None
