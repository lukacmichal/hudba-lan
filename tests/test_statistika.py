"""Testy databazy prehrati (music_player.statistika) a jej napojenia na
pocitadlo v PlayerControlleri.

Standalone (pytest v tomto prostredi je rozbity):
    python tests/test_statistika.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_player.models import Track  # noqa: E402
from music_player.statistika import Statistika  # noqa: E402

DEN = 86_400
TERAZ = 1_800_000_000.0  # cas sa dava explicitne, time.time() ma hruby krok


def _db():
    return Statistika(Path(tempfile.mkdtemp()) / "statistika.db")


def _t(nazov, interpret="Kapela", album="Album", dlzka=200_000):
    return Track(path=f"C:/mp3/{interpret}/{nazov}.mp3", title=nazov,
                 artist=interpret, album=album, duration_ms=dlzka)


def test_poradie_podla_poctu():
    s = _db()
    a, b = _t("A"), _t("B")
    for _ in range(3):
        s.zaznamenaj(a, TERAZ - 10)
    s.zaznamenaj(b, TERAZ - 5)
    rows = s.skladby(teraz=TERAZ)
    assert [(r.popis, r.pocet) for r in rows] == [("Kapela – A", 3), ("Kapela – B", 1)], rows
    assert rows[0].naposledy == TERAZ - 10


def test_obdobie_filtruje():
    s = _db()
    a, b = _t("A"), _t("B")
    s.zaznamenaj(a, TERAZ - 40 * DEN)
    s.zaznamenaj(a, TERAZ - 35 * DEN)
    s.zaznamenaj(b, TERAZ - 2 * DEN)
    assert [r.popis for r in s.skladby(7, teraz=TERAZ)] == ["Kapela – B"]
    assert s.skladby(None, teraz=TERAZ)[0].popis == "Kapela – A"
    assert s.suhrn(30, teraz=TERAZ) == (1, 1, 200_000)
    assert s.suhrn(None, teraz=TERAZ) == (3, 2, 600_000)


def test_interpreti_a_albumy():
    s = _db()
    s.zaznamenaj(_t("A", "Behemoth", "I Loved You"), TERAZ - 3)
    s.zaznamenaj(_t("B", "Behemoth", "I Loved You"), TERAZ - 2)
    s.zaznamenaj(_t("C", "Mgła", "Age"), TERAZ - 1)
    assert [(r.popis, r.pocet) for r in s.interpreti(teraz=TERAZ)] == [("Behemoth", 2), ("Mgła", 1)]
    assert [(r.popis, r.pocet) for r in s.albumy(teraz=TERAZ)] == [
        ("Behemoth – I Loved You", 2), ("Mgła – Age", 1)]


def test_metadata_z_posledneho_prehratia():
    s = _db()
    stary = _t("zly nazov")
    novy = Track(path=stary.path, title="Dobrý názov", artist="Kapela")
    s.zaznamenaj(stary, TERAZ - 10)
    s.zaznamenaj(novy, TERAZ - 1)
    rows = s.skladby(teraz=TERAZ)
    assert len(rows) == 1 and rows[0].pocet == 2
    assert rows[0].popis == "Kapela – Dobrý názov", rows[0].popis


def test_historia_najnovsie_prve():
    s = _db()
    s.zaznamenaj(_t("A"), TERAZ - 10)
    s.zaznamenaj(_t("B"), TERAZ - 1)
    assert [r.popis for r in s.historia()] == ["Kapela – B", "Kapela – A"]
    assert s.pocet(_t("A").path) == 1


def test_bez_interpreta_nazov_zo_suboru():
    s = _db()
    s.zaznamenaj(Track(path="C:/mp3/x/01 Intro.mp3", title=""), TERAZ)
    assert s.skladby(teraz=TERAZ)[0].popis == "01 Intro"
    assert s.interpreti(teraz=TERAZ) == []


def test_prezije_restart():
    s = _db()
    s.zaznamenaj(_t("A"), TERAZ)
    s.zavri()
    s2 = Statistika(s.cesta)
    assert s2.pocet(_t("A").path) == 1


def test_zla_cesta_nezhodi_prehravanie():
    # Priecinok namiesto suboru -> sqlite chyba; zapis len vrati False.
    s = Statistika(Path(tempfile.mkdtemp()))
    assert s.zaznamenaj(_t("A"), TERAZ) is False
    assert s.skladby() == []


def test_controller_zapise_raz_za_prehratie():
    # Pomocne funkcie z druheho testu; import podla cesty, lebo `tests` nie je
    # balik a v site-packages moze byt iny modul s tym menom.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "test_listen_stats", Path(__file__).with_name("test_listen_stats.py"))
    listen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(listen)
    _advance, _make = listen._advance, listen._make

    c = _make()
    c.statistika = _db()
    c.playlist = [_t("A")]
    c.current_index = 0
    _advance(c, 0, 10_000, 29_000)
    assert c.statistika.pocet(_t("A").path) == 0     # preskocena sa neráta
    _advance(c, 30_000, 60_000, 120_000)
    assert c.statistika.pocet(_t("A").path) == 1
    c._reset_track_accounting()
    _advance(c, 0, 30_000)
    assert c.statistika.pocet(_t("A").path) == 2


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {type(exc).__name__}: {exc}")
    sys.exit(1 if failures else 0)
