"""Okno "Z Downloads": nahlad nazvov, ich uprava a co z toho ide do `vykonaj`.

Archivy su skutocne zipy v tmp_path, okno bezi mimo obrazovky. Kontroluje
sa, ze priecinok v nahlade je ten, ktory sa naozaj vytvori, a ze sa nic
nezmaze ani nerozbali bez zaskrtnutia.
"""
import os
import sys
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from music_player import downloads_import as di  # noqa: E402
from music_player.ui import _DownloadsDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _zip(folder: Path, meno: str, polozky: list[str]) -> Path:
    with zipfile.ZipFile(folder / meno, "w") as zf:
        for polozka in polozky:
            zf.writestr(polozka, b"x" * 16)
    return folder / meno


@pytest.fixture
def okno(app, tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    _zip(downloads, "a.zip", ["Kapela - Album (2026)/01.mp3", "Kapela - Album (2026)/02.mp3"])
    _zip(downloads, "b.zip", ["Blind-Guardian-Somewhere-2026-GRP/01.mp3"])
    _zip(downloads, "c.zip", ["Stara - Vec (2025)/01.mp3"])
    (downloads / "d.rar").write_bytes(b"nie archiv")
    root = tmp_path / "mp3"
    (di.target_dir(root) / "Stara - Vec - 2025").mkdir(parents=True)

    dlg = _DownloadsDialog(None, di.nacitaj(downloads, root=root))
    yield dlg
    dlg.deleteLater()


def _riadok(dlg, archiv: str) -> int:
    return next(i for i, n in enumerate(dlg._navrhy) if n.archive.name == archiv)


def _zaskrtnute(dlg, stlpec: int) -> list[str]:
    return [n.archive.name for i, n in enumerate(dlg._navrhy) if dlg._zaskrtnute(i, stlpec)]


def test_predvolene_sa_rozbali_len_nove_a_nic_sa_nemaze(okno):
    assert _zaskrtnute(okno, okno.ROZBALIT) == ["a.zip", "b.zip"]
    assert _zaskrtnute(okno, okno.ZMAZAT) == []
    assert okno._text(_riadok(okno, "c.zip"), okno.STAV) == "už rozbalené"
    assert okno._text(_riadok(okno, "d.rar"), okno.STAV).startswith("nedá sa prečítať")
    assert okno._text(_riadok(okno, "b.zip"), okno.STAV) == "nové — názvu nerozumiem, skontroluj"


def test_nahlad_ukazuje_rocny_priecinok_a_nazov(okno):
    r = _riadok(okno, "a.zip")
    assert okno._text(r, okno.PRIECINOK) == f"{okno._target.name}\\Kapela - Album - 2026"
    assert okno._text(_riadok(okno, "d.rar"), okno.PRIECINOK) == ""


def test_uprava_zmeni_priecinok_aj_ulohu(okno):
    r = _riadok(okno, "b.zip")
    okno._tabulka.item(r, okno.SKUPINA).setText("Blind Guardian")
    okno._tabulka.item(r, okno.ALBUM).setText("Somewhere")
    okno._tabulka.item(r, okno.ROK).setText("2026")

    assert okno._text(r, okno.PRIECINOK).endswith("\\Blind Guardian - Somewhere - 2026")
    assert okno._text(r, okno.STAV) == "nové — upravené"
    uloha = next(u for u in okno.ulohy() if u.archive.name == "b.zip")
    assert uloha.nazov == "Blind Guardian - Somewhere - 2026"
    # Neupraveny navrh z nazvu ide bez nazvu — odvodi sa z disku.
    assert next(u for u in okno.ulohy() if u.archive.name == "a.zip").nazov is None


def test_premenovanie_na_existujuci_album(okno):
    r = _riadok(okno, "a.zip")
    okno._tabulka.item(r, okno.SKUPINA).setText("Stara")
    okno._tabulka.item(r, okno.ALBUM).setText("Vec")
    okno._tabulka.item(r, okno.ROK).setText("2025")

    assert okno._text(r, okno.STAV) == "už rozbalené"


def test_rovnaky_priecinok_dvakrat(okno):
    r = _riadok(okno, "b.zip")
    okno._tabulka.item(r, okno.SKUPINA).setText("Kapela")
    okno._tabulka.item(r, okno.ALBUM).setText("Album")
    okno._tabulka.item(r, okno.ROK).setText("2026")

    assert okno._text(r, okno.STAV).startswith("rovnaký priečinok")
    assert "1 album" in okno._suhrn.text()


def test_prazdny_nazov_zablokuje_vykonanie(okno):
    r = _riadok(okno, "a.zip")
    for stlpec in (okno.SKUPINA, okno.ALBUM, okno.ROK):
        okno._tabulka.item(r, stlpec).setText("")

    assert okno._text(r, okno.STAV) == "chýba názov"
    assert not okno._ok.isEnabled()


def test_rozbalit_vsetky_naraz_a_spat(okno):
    for r in range(len(okno._navrhy)):
        okno._tabulka.item(r, okno.ROZBALIT).setCheckState(Qt.CheckState.Unchecked)
    assert okno._vsetky_button.text() == "☑ Rozbaliť všetky"

    okno._rozbalit_vsetky()
    # Uz rozbaleny (c) a necitatelny (d) sa nezaskrtnu — nic by sa s nimi nestalo.
    assert _zaskrtnute(okno, okno.ROZBALIT) == ["a.zip", "b.zip"]
    assert okno._vsetky_button.text() == "☐ Nerozbaliť nič"

    okno._rozbalit_vsetky()
    assert _zaskrtnute(okno, okno.ROZBALIT) == []
    assert not okno._ok.isEnabled()


def test_zmazat_uz_rozbalene(okno):
    okno._zmazat_hotove()

    assert _zaskrtnute(okno, okno.ZMAZAT) == ["c.zip"]
    uloha, = [u for u in okno.ulohy() if u.zmazat]
    assert (uloha.archive.name, uloha.rozbalit) == ("c.zip", False)


def test_hlavicka_prepne_cely_stlpec(okno):
    okno._prepni_stlpec(okno.ZMAZAT)
    assert _zaskrtnute(okno, okno.ZMAZAT) == ["a.zip", "b.zip", "c.zip", "d.rar"]
    assert "z toho nerozbalené" not in okno._suhrn.text()  # a, b sa rozbalia

    okno._prepni_stlpec(okno.ZMAZAT)
    assert _zaskrtnute(okno, okno.ZMAZAT) == []

    # Necitatelny archiv sa rozbalit neda — prepnutie ho obide.
    okno._prepni_stlpec(okno.ROZBALIT)
    assert "d.rar" not in _zaskrtnute(okno, okno.ROZBALIT)


def test_nerozbaleny_na_zmazanie_je_v_suhrne(okno):
    r = _riadok(okno, "a.zip")
    okno._tabulka.item(r, okno.ROZBALIT).setCheckState(Qt.CheckState.Unchecked)
    okno._tabulka.item(r, okno.ZMAZAT).setCheckState(Qt.CheckState.Checked)

    assert "z toho nerozbalené: 1" in okno._suhrn.text()


def test_prehodit_a_vratit_navrh(okno):
    r = _riadok(okno, "a.zip")
    okno._tabulka.selectRow(r)

    okno._prehod()
    assert okno._hodnoty(r) == ("Album", "Kapela", "2026")

    okno._nastav_vybrane(lambda n: (n.interpret, n.album, str(n.rok or "")))
    assert okno._hodnoty(r) == ("Kapela", "Album", "2026")

    okno._nastav_vybrane(lambda n: ("", n.surovy, ""))
    assert okno._text(r, okno.PRIECINOK).endswith("\\Kapela - Album (2026)")
