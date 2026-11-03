"""Pozadie plochy podla albumu (music_player/pozadie_plochy.py).

Windows sa tu nemeni: IDesktopWallpaper aj registre su nahradene falosnymi,
logika (co sa zapamata, kedy sa vracia, co sa necha tak) bezi naostro.
Skutocne nastavenie a vratenie pozadia je overene rucne — HUDBA-20.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from music_player import pozadie_plochy as pp  # noqa: E402


def _jpg(farba: str, velkost: int = 200) -> bytes:
    img = QImage(velkost, velkost, QImage.Format.Format_RGB32)
    img.fill(QColor(farba))
    pole = QByteArray()
    buf = QBuffer(pole)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPG")
    return bytes(pole)


class FalosnyWallpaper:
    """Stav plochy zdielany medzi instanciami (ako skutocny Windows)."""
    plocha: dict = {}
    poz = 4
    stav_prezentacie = 0

    def __init__(self) -> None:
        pass

    def monitory(self):
        return list(self.plocha)

    def zapojene(self):
        return [(m, 640, 360) for m in self.plocha]

    def pozadie(self, monitor):
        return self.plocha[monitor]

    def nastav(self, monitor, cesta):
        self.plocha[monitor] = cesta

    def pozicia(self):
        return FalosnyWallpaper.poz

    def nastav_poziciu(self, pozicia):
        FalosnyWallpaper.poz = pozicia

    def stav(self):
        return self.stav_prezentacie

    def uvolni(self):
        pass


def _priprav(tmp_path, monkeypatch, *, typ=None):
    povodny = tmp_path / "moje-pozadie.jpg"
    povodny.write_bytes(_jpg("#336699"))
    FalosnyWallpaper.plocha = {"MON1": str(povodny)}
    FalosnyWallpaper.poz = 10
    FalosnyWallpaper.stav_prezentacie = 0
    historia = {"BackgroundHistoryPath0": str(povodny), "BackgroundHistoryPath1": "c:\\x.jpg"}
    registre = dict(historia)
    if typ is not None:
        registre["BackgroundType"] = typ
    zapisana = {}
    monkeypatch.setattr(pp, "_DesktopWallpaper", FalosnyWallpaper)
    monkeypatch.setattr(pp, "_citaj_wallpapers", lambda: dict(registre))
    monkeypatch.setattr(pp, "_zapis_historiu", lambda h: zapisana.update(h))
    monkeypatch.setattr(pp, "_transcoded", lambda i: None)
    pozadie = pp.PozadiePlochy(tmp_path / "pozadie")
    return pozadie, povodny, zapisana


def _album(farba="#aa2200", kluc="kapela|album|1"):
    return pp.Album(kluc=kluc, obal=_jpg(farba), interpret="Kapela", album="Album", rok="2026")


def test_farby_z_obalu_vyrazny_akcent():
    f = pp.farby_z_obalu(_jpg("#c02010"))
    assert set(f) == {"pozadie", "lista", "akcent", "text"}
    akcent = QColor(f["akcent"])
    assert akcent.red() > akcent.green() and akcent.red() > akcent.blue()
    # Pozadie je tmave, text svetly — inak by Firefox s temou nebol citatelny.
    assert QColor(f["pozadie"]).lightnessF() < 0.2
    assert QColor(f["text"]).lightnessF() > 0.85


def test_farby_ciernobiely_obal_sivy_akcent():
    assert pp.farby_z_obalu(_jpg("#808080"))["akcent"] == "#c8c8c8"


def test_farby_bez_obalu():
    assert pp.farby_z_obalu(None) is None
    assert pp.farby_z_obalu(b"toto nie je obrazok") is None


def test_obrazok_ma_presne_rozlisenie_monitora():
    img = pp.zloz_obrazok(_jpg("#204060"), 1280, 720, interpret="A", album="B", rok="2026")
    assert (img.width(), img.height()) == (1280, 720)
    assert pp.zloz_obrazok(b"zle", 1280, 720) is None


def test_album_na_plochu_a_spat(tmp_path, monkeypatch):
    pozadie, povodny, historia = _priprav(tmp_path, monkeypatch)
    pozadie._ukaz(_album())
    assert pozadie.aktivne
    na_ploche = FalosnyWallpaper.plocha["MON1"]
    assert Path(na_ploche).parent == tmp_path / "pozadie" and Path(na_ploche).name.startswith("album-")
    assert FalosnyWallpaper.poz == pp.POZICIA_VYPLNIT
    zaznam = json.loads(pozadie.subor_stavu.read_text(encoding="utf-8"))
    assert zaznam["monitory"]["MON1"] == str(povodny)
    assert zaznam["pozicia"] == 10

    pozadie._vrat()
    assert FalosnyWallpaper.plocha["MON1"] == str(povodny)
    assert FalosnyWallpaper.poz == 10
    assert historia["BackgroundHistoryPath0"] == str(povodny)
    assert not pozadie.subor_stavu.exists()
    assert not pozadie.aktivne
    assert not list((tmp_path / "pozadie").glob("album-*"))


def test_rovnaky_album_sa_nekresli_znova(tmp_path, monkeypatch):
    pozadie, _, _ = _priprav(tmp_path, monkeypatch)
    pozadie._ukaz(_album())
    prvy = FalosnyWallpaper.plocha["MON1"]
    pozadie._ukaz(_album())
    assert FalosnyWallpaper.plocha["MON1"] == prvy
    pozadie._ukaz(_album("#0033cc", kluc="ina|kapela|2"))
    assert FalosnyWallpaper.plocha["MON1"] != prvy


def test_pozadie_zmenene_clovekom_sa_neprepisuje(tmp_path, monkeypatch):
    pozadie, _, _ = _priprav(tmp_path, monkeypatch)
    pozadie._ukaz(_album())
    FalosnyWallpaper.plocha["MON1"] = "C:\\nove-od-cloveka.jpg"
    pozadie._vrat()
    assert FalosnyWallpaper.plocha["MON1"] == "C:\\nove-od-cloveka.jpg"
    assert "nechávam" in pozadie.stav


def test_po_zmene_clovekom_je_jeho_volba_nove_povodne(tmp_path, monkeypatch):
    pozadie, _, _ = _priprav(tmp_path, monkeypatch)
    pozadie._ukaz(_album())
    nove = tmp_path / "nove.jpg"
    nove.write_bytes(_jpg("#00ff00"))
    FalosnyWallpaper.plocha["MON1"] = str(nove)
    pozadie._ukaz(_album("#0033cc", kluc="ina|kapela|2"))
    pozadie._vrat()
    assert FalosnyWallpaper.plocha["MON1"] == str(nove)


def test_prezentaciu_ani_spotlight_nemeni(tmp_path, monkeypatch):
    for typ in (2, 3):
        pozadie, povodny, _ = _priprav(tmp_path, monkeypatch, typ=typ)
        pozadie._ukaz(_album())
        assert FalosnyWallpaper.plocha["MON1"] == str(povodny)
        assert not pozadie.aktivne
        assert "nemením" in pozadie.stav
        assert not pozadie.subor_stavu.exists()


def test_po_pade_sa_pozadie_vrati_pri_starte(tmp_path, monkeypatch):
    pozadie, povodny, _ = _priprav(tmp_path, monkeypatch)
    pozadie._ukaz(_album())
    # Appka spadla: novy beh, nova instancia, ziadny stav v pamati.
    dalsi = pp.PozadiePlochy(tmp_path / "pozadie")
    dalsi._obnov_po_pade()
    assert FalosnyWallpaper.plocha["MON1"] == str(povodny)
    assert not dalsi.subor_stavu.exists()


def test_zmazany_povodny_obrazok_sa_vrati_z_kopie(tmp_path, monkeypatch):
    pozadie, povodny, _ = _priprav(tmp_path, monkeypatch)
    pozadie._ukaz(_album())
    povodny.unlink()
    pozadie._vrat()
    vratene = Path(FalosnyWallpaper.plocha["MON1"])
    assert vratene.name.startswith("obnovene-") and vratene.is_file()


def test_kluc_albumu_zavisi_od_obalu():
    assert pp.kluc_albumu("A", "B", b"1") == pp.kluc_albumu("a ", "b", b"1")
    assert pp.kluc_albumu("A", "B", b"1") != pp.kluc_albumu("A", "B", b"2")
