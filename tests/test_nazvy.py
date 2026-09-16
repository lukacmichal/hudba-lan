"""Testy pre upratanie nazvov albumovych priecinkov."""

from __future__ import annotations

import datetime as dt

import pytest

from music_player import nazvy


@pytest.mark.parametrize("surovy, cakane", [
    # Tvar, ktory prisiel z metalarea — kvoli nemu to cele vzniklo.
    ("Dark Plague`2026`Masquerade by necroscum", "Dark Plague - Masquerade - 2026"),
    ("Dark Plague`Masquerade`2026", "Dark Plague - Masquerade - 2026"),
    # Uz spravny nazov sa nesmie zmenit — inak by sa album pri kazdom
    # rozbaleni volal inak.
    ("Dark Plague - Masquerade - 2026", "Dark Plague - Masquerade - 2026"),
    # Rok v zatvorke aj v hranatej
    ("Avulsed - Nordic Embryogenesis (2026)", "Avulsed - Nordic Embryogenesis - 2026"),
    ("Avulsed - Nordic Embryogenesis [2026]", "Avulsed - Nordic Embryogenesis - 2026"),
    # Podtrzitka namiesto medzier
    ("Band_-_Album_-_2026", "Band - Album - 2026"),
    ("Kapela_-_Album_(2026)", "Kapela - Album - 2026"),
    # Balicek: format a kvalita v nazve nemaju co robit
    ("Various Artists - Tribute (2015) [FLAC]", "Various Artists - Tribute - 2015"),
    ("Kapela - Album [WEB] [320kbps] - 2026", "Kapela - Album - 2026"),
    # Rok pred albumom aj za nim
    ("Kapela - 2026 - Album", "Kapela - Album - 2026"),
    # Bez roku sa nic nedomyslia
    ("Behemoth - I, Scvlptor", "Behemoth - I, Scvlptor"),
    # Dlha pomlcka z webu
    ("Kapela – Album – 2026", "Kapela - Album - 2026"),
])
def test_uprav(surovy, cakane):
    assert nazvy.uprav(surovy) == cakane


@pytest.mark.parametrize("surovy", [
    # Holá pomlcka bez medzier: kde konci album a zacina meno skupiny sa uhadnut
    # neda, tak sa nazov necha tak.
    "Blind-Guardian-Somewhere-2026-GRP",
    # Jedno slovo nie je "interpret - album"
    "nejaky_divny_nazov",
    "Album",
    "",
])
def test_necitatelny_nazov_zostava(surovy):
    assert nazvy.uprav(surovy) == surovy


def test_rok_musi_byt_hodnoverny():
    """`2999` je cislo v nazve albumu, nie rok vydania."""
    assert nazvy.uprav("Kapela - Album 2999") == "Kapela - Album 2999"
    buduci = dt.date.today().year + 1
    assert nazvy.uprav(f"Kapela - Album - {buduci}") == f"Kapela - Album - {buduci}"


def test_by_releasera_sa_zahodi_len_jedno_slovo():
    assert nazvy.rozober("Kapela`2026`Album by necroscum").album == "Album"
    # Album sa naozaj moze volat "Songs By The Dead" — to sa oklestit nesmie.
    assert nazvy.rozober("Kapela - Songs By The Dead").album == "Songs By The Dead"


def test_pripona_archivu_sa_nedostane_do_nazvu():
    assert nazvy.uprav("Kapela - Album - 2026.rar") == "Kapela - Album - 2026"


def test_viac_casti_sa_spoji_spat():
    """`A - B - C` bez roku je album s pomlckou v nazve, nie tri polia."""
    assert nazvy.uprav("Kapela - Album - Cast II") == "Kapela - Album - Cast II"


def test_kluc_zahadzuje_interpunkciu():
    """Nazov priecinka a zaznam zo skenu sa musia stretnut aj s inou interpunkciou."""
    assert nazvy.kluc("Augurium", "Faith & Death") == nazvy.kluc("augurium", "Faith and Death")
    assert nazvy.kluc("Nails", "You Will Never Be One Of Us") == \
        nazvy.kluc("NAILS", "You Will Never Be One of Us")


def test_kluc_zahadzuje_aj_diakritiku():
    """Sken pise `Boötes Void`, priecinok byva `Bootes Void` — musia sa stretnut."""
    assert nazvy.kluc("Boötes Void", "Panta Rhei") == "bootes void|panta rhei"
    assert nazvy.kluc("Bootes Void", "Panta Rhei") == nazvy.kluc("Boötes Void", "Panta Rhei")


# ── rozlozenie na slova a hladanie zhody ──────────────────────────────────────
def test_rozlozenie_vyhodi_rok_a_ozdoby():
    assert nazvy.rozlozenie("Blind-Guardian-Somewhere-2026-GRP") == (
        ["blind", "guardian", "somewhere", "grp"], 2026)
    assert nazvy.rozlozenie("Dark Plague`2026`Masquerade by necroscum") == (
        ["dark", "plague", "masquerade"], 2026)


def test_najdi_v_zozname_zniesie_meno_skupiny_na_konci():
    """`-GRP` v nazve neprekaza: rozhoduje, ci su slova z MA obsiahnute v nazve."""
    najdene = nazvy.najdi_v_zozname(
        "Dysphorectomy-Forever-2026-GRP",
        [("Dysphorectomy", "Demo 2024"), ("Dysphorectomy", "Forever")])
    assert najdene.text == "Dysphorectomy - Forever - 2026"


def test_najdi_v_zozname_uprednostni_viac_pokrytych_slov():
    """Samotitulny album pokryva jedno slovo, spravny dve — nesmie vyhrat poradim."""
    najdene = nazvy.najdi_v_zozname(
        "Dysphorectomy-Forever-2026-GRP",
        [("Dysphorectomy", "Dysphorectomy"), ("Dysphorectomy", "Forever")])
    assert najdene.album == "Forever"


def test_najdi_v_zozname_uprednostni_dlhsi_nazov():
    najdene = nazvy.najdi_v_zozname(
        "Blind Guardian - Somewhere Far Beyond - 1992",
        [("Blind Guardian", "Somewhere"), ("Blind Guardian", "Somewhere Far Beyond")])
    assert najdene.album == "Somewhere Far Beyond"


def test_najdi_v_zozname_netipuje():
    """Ked v nazve nie su vsetky slova kapely aj albumu, nevracia sa nic."""
    kandidati = [("Blind Guardian", "Somewhere Far Beyond")]
    assert nazvy.najdi_v_zozname("Blind-Guardian-Somewhere-2026-GRP", kandidati) is None
    assert nazvy.najdi_v_zozname("uplne ine meno", kandidati) is None
    assert nazvy.najdi_v_zozname("", kandidati) is None


def test_najdi_v_zozname_zniesie_diakritiku_a_ampersand():
    assert nazvy.najdi_v_zozname(
        "Bootes-Void-Panta-Rhei-2026", [("Boötes Void", "Panta Rhei")]
    ).interpret == "Boötes Void"
    assert nazvy.najdi_v_zozname(
        "Augurium - Faith and Death - 2026", [("Augurium", "Faith & Death")]
    ).album == "Faith & Death"
