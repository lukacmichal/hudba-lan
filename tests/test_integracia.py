"""Napojenie na Windows a Firefox (music_player/integracia.py a spol.).

Pozadie plochy, okienko medii ani panel uloh sa tu naozaj nezapinaju —
integracia dostane falosne pozadie a overuje sa, KEDY ho meni: aby
pozadie pri prechode medzi skladbami neblikalo, aby stop po pauze necakal
5 minut a aby API drzalo posledny obal, kym nepride novy.
"""
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from music_player import firefox_rozsirenie, integracia, kniznice  # noqa: E402
from music_player.metadata_server import NowPlayingServer  # noqa: E402
from music_player.models import Track  # noqa: E402


class FalosnyPrehravac:
    def __init__(self):
        self.pozicia = 0
        self.dlzka = 200_000

    def position(self):
        return self.pozicia

    def duration(self):
        return self.dlzka


class FalosnyController(QObject):
    current_track_changed = Signal(object)
    playback_state_changed = Signal(str)
    position_changed = Signal(int)
    duration_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.player = FalosnyPrehravac()
        self.stav = "stopped"
        self.skladba = None
        self.posuny = []

    def current_track(self):
        return self.skladba

    def playback_state_name(self):
        return self.stav

    def seek(self, ms):
        self.posuny.append(ms)

    def zmen(self, stav=None, skladba=None):
        if skladba is not None:
            self.skladba = skladba
            self.current_track_changed.emit(skladba)
        if stav is not None:
            self.stav = stav
            self.playback_state_changed.emit(stav)


class FalosneOkno(QObject):
    obal_zobrazeny = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.prepnute = 0
        self.obal_posledny = None

    def _toggle_playback_from_ui(self):
        self.prepnute += 1


class FalosnePozadie:
    def __init__(self):
        self.ukazane = []
        self.vratene = 0
        self.aktivne = False
        self.stav = "test"

    def spusti(self):
        pass

    def ukaz(self, album):
        self.ukazane.append(album)
        self.aktivne = True

    def vrat(self, pockaj=0.0):
        self.vratene += 1
        self.aktivne = False

    def zastav(self, pockaj=0.0):
        self.vrat()


def _integracia(monkeypatch):
    monkeypatch.setattr(integracia, "load_config", lambda: {
        "POZADIE_PLOCHY": "ano", "OVLADANIE_MEDII": "nie", "PANEL_ULOH": "nie"})
    monkeypatch.setattr(integracia, "PozadiePlochy", FalosnePozadie)
    controller = FalosnyController()
    okno = FalosneOkno()
    i = integracia.WindowsIntegracia(controller, okno)
    i.spusti()
    return i, controller, okno


def _skladba(cislo, album="Album"):
    return Track(path=f"C:\\hudba\\{album}\\{cislo:02d}.mp3", title=f"Skladba {cislo}",
                 artist="Kapela", album=album, year="2026")


def _obal(farba=b"\x01"):
    # Hlavicka JPEG staci — integracia obsah neskuma, len ho posiela dalej.
    return b"\xff\xd8\xff\xe0" + farba * 2000


def test_album_ide_na_plochu_az_ked_hra_a_ma_obal(monkeypatch):
    i, c, okno = _integracia(monkeypatch)
    s1 = _skladba(1)
    c.zmen(skladba=s1)
    okno.obal_zobrazeny.emit(s1.path, _obal())
    assert i.pozadie.ukazane == []          # nehra
    c.zmen(stav="playing")
    assert len(i.pozadie.ukazane) == 1
    assert i.pozadie.ukazane[0].album == "Album" and i.pozadie.ukazane[0].rok == "2026"
    polia = i.api_polia()
    assert polia["albumAktivny"] is True and polia["obalVerzia"] and polia["album"] == "Album"


def test_dalsia_skladba_toho_isteho_albumu_neblika(monkeypatch):
    i, c, okno = _integracia(monkeypatch)
    s1, s2 = _skladba(1), _skladba(2)
    c.zmen(skladba=s1, stav="playing")
    okno.obal_zobrazeny.emit(s1.path, _obal())
    verzia = i.api_polia()["obalVerzia"]
    # Prechod: stop -> nova skladba -> hra, obal novej este nedorazil.
    c.zmen(stav="stopped")
    c.zmen(skladba=s2, stav="playing")
    assert i.pozadie.vratene == 0
    assert i.api_polia()["obalVerzia"] == verzia      # Firefox drzi temu
    okno.obal_zobrazeny.emit(s2.path, _obal())
    assert i.pozadie.vratene == 0


def test_skladba_bez_obalu_vrati_povodne(monkeypatch):
    i, c, okno = _integracia(monkeypatch)
    s1, s2 = _skladba(1), _skladba(1, album="Ine")
    c.zmen(skladba=s1, stav="playing")
    okno.obal_zobrazeny.emit(s1.path, _obal())
    c.zmen(skladba=s2)
    okno.obal_zobrazeny.emit(s2.path, None)
    assert i.pozadie.vratene == 1
    assert i.api_polia()["albumAktivny"] is False


def test_pauza_caka_5_minut_stop_15_sekund(monkeypatch):
    i, c, okno = _integracia(monkeypatch)
    s1 = _skladba(1)
    c.zmen(skladba=s1, stav="playing")
    okno.obal_zobrazeny.emit(s1.path, _obal())
    c.zmen(stav="paused")
    assert i._navrat.isActive() and i._navrat.remainingTime() > 60_000
    # Stop po pauze nema cakat zvysok z 5 minut.
    c.zmen(stav="stopped")
    assert i._navrat.remainingTime() <= integracia.STOP_DO_NAVRATU_MS
    c.zmen(stav="playing")
    assert not i._navrat.isActive()
    c.zmen(stav="stopped")
    i._album_skoncil()
    assert i.pozadie.vratene == 1
    assert i.api_polia()["albumAktivny"] is False


def test_vypnute_pozadie_sa_nemeni(monkeypatch):
    i, c, okno = _integracia(monkeypatch)
    i.pozadie_zapnute = False
    s1 = _skladba(1)
    c.zmen(skladba=s1, stav="playing")
    okno.obal_zobrazeny.emit(s1.path, _obal())
    assert i.pozadie.ukazane == []
    # Firefox ide dalej podla albumu — ma vlastny vypinac.
    assert i.api_polia()["albumAktivny"] is True


def test_tlacidla_z_windows(monkeypatch):
    i, c, okno = _integracia(monkeypatch)
    c.next_track = lambda: setattr(c, "dalsia", True)
    c.stav = "playing"
    i._na_tlacidlo_medii("play")      # uz hra -> nic
    assert okno.prepnute == 0
    i._na_tlacidlo_medii("pause")
    assert okno.prepnute == 1
    i._na_tlacidlo_medii("next")
    assert c.dalsia


def test_obal_do_api(monkeypatch):
    i, c, okno = _integracia(monkeypatch)
    assert i.obal_pre_api() is None
    s1 = _skladba(1)
    c.zmen(skladba=s1)
    okno.obal_zobrazeny.emit(s1.path, _obal())
    data, typ = i.obal_pre_api()
    assert typ == "image/jpeg" and len(data) > 1000
    assert integracia._typ_obrazka(b"\x89PNG\r\n\x1a\n...") == "image/png"


# ── server ─────────────────────────────────────────────────────────────────
def test_server_cover_a_health():
    srv = NowPlayingServer(
        payload_provider=lambda: {"state": "playing", "album": "X"},
        preferred_port=0,
        cover_provider=lambda: (b"\xff\xd8obal", "image/jpeg"),
        health_provider=lambda: {"pozadie": "zapnuté"},
    )
    srv.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/api/cover?v=abc", timeout=3) as r:
            assert r.read() == b"\xff\xd8obal"
            assert r.headers["Content-Type"] == "image/jpeg"
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/health", timeout=3) as r:
            h = json.loads(r.read())
            assert h["status"] == "ok" and h["integracia"] == {"pozadie": "zapnuté"}
    finally:
        srv.stop()


def test_server_bez_obalu_404():
    srv = NowPlayingServer(payload_provider=lambda: {}, preferred_port=0, cover_provider=lambda: None)
    srv.start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/api/cover", timeout=3)
            assert False, "malo byt 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


# ── kniznice ───────────────────────────────────────────────────────────────
def test_kniznice_chybaju_bez_importu():
    assert kniznice.chybaju(("balik-co-neexistuje-xyz",)) == ["balik-co-neexistuje-xyz"]
    assert kniznice.chybaju(("PySide6",)) == []


# ── Firefox ────────────────────────────────────────────────────────────────
def test_firefox_verzie():
    assert firefox_rozsirenie.novsia("1.10", "1.9")
    assert not firefox_rozsirenie.novsia("1.2", "1.2")


def _xpi(cesta: Path, ident: str, verzia: str) -> Path:
    with zipfile.ZipFile(cesta, "w") as z:
        z.writestr("manifest.json", json.dumps({
            "name": ident, "version": verzia,
            "browser_specific_settings": {"gecko": {"id": ident}}}))
    return cesta


def test_firefox_co_treba_nainstalovat(tmp_path, monkeypatch):
    import music_player.self_update as su
    monkeypatch.setattr(su, "prihlas_na_share", lambda p: False)
    _xpi(tmp_path / "metalmusic-firefox-1.1.xpi", firefox_rozsirenie.HLAVNE_ID, "1.1")
    _xpi(tmp_path / "metalmusic-firefox-1.2.xpi", firefox_rozsirenie.HLAVNE_ID, "1.2")
    _xpi(tmp_path / "mmp-tlacidlo-next-1.0.xpi", "mmp-dalsia@lukacmichal", "1.0")
    na_nase = firefox_rozsirenie.na_nas(tmp_path)
    assert [(b.id, b.verzia) for b in na_nase][0] == (firefox_rozsirenie.HLAVNE_ID, "1.2")
    treba = firefox_rozsirenie.treba_nainstalovat(
        na_nase, {firefox_rozsirenie.HLAVNE_ID: "1.1", "mmp-dalsia@lukacmichal": "1.0"})
    assert [b.verzia for b in treba] == ["1.2"]
    assert firefox_rozsirenie.treba_nainstalovat(na_nase, {}) == na_nase


def test_firefox_nainstalovane_z_profilu(tmp_path):
    (tmp_path / "extensions.json").write_text(json.dumps({"addons": [
        {"id": firefox_rozsirenie.HLAVNE_ID, "version": "1.1", "location": "app-profile"},
        {"id": "cudzie@niekto", "version": "9", "location": "app-profile"},
        {"id": "mmp-hraj@lukacmichal", "version": "1.0", "location": "app-temporary"},
    ]}), encoding="utf-8")
    assert firefox_rozsirenie.nainstalovane(tmp_path) == {firefox_rozsirenie.HLAVNE_ID: "1.1"}


def test_farba_startu_len_cita():
    stav = integracia.farba_startu()
    assert set(stav) == {"automaticka", "naStarte", "tmavy"}
    assert isinstance(integracia.farba_startu_popis(), str)


def test_okno_bez_integracie_sa_neda_zrutit():
    # MainWindow.nativeEvent s integracia = None nesmie nic robit.
    from music_player.ui import MainWindow
    okno = SimpleNamespace(integracia=None)
    assert MainWindow.nativeEvent(okno, b"windows_generic_MSG", 0) == (False, 0)
