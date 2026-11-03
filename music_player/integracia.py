"""Napojenie prehravaca na Windows a Firefox.

Spaja tri samostatne casti s prehravacom:

* `pozadie_plochy` — obal albumu ako pozadie plochy (a s automatickou
  farbou zvyraznenia vo Windows aj farba Startu a panela uloh),
* `windows_media` — okienko medii vo Windows, medialne klavesy, sluchadla,
* `panel_uloh` — tlacidla ⏮ ⏯ ⏭ v nahlade okna a priebeh skladby v ikone,

a pre Firefox (aj telefon, keby chcel) posiela cez API obal a farby albumu.

Ziadna z tychto casti nemeni nic na tom, ako prehravac hra, streamuje, ako
sa ovlada z telefonu alebo uspava — len pocuva jeho signaly. Kazda sa da
vypnut v okne „🪟 Windows" (zapise sa do config.txt) a ked zlyha, prehravac
ide dalej bez nej.

Kedy je album „aktivny" (pozadie plochy a farby Firefoxu ukazuju album):
hra hudba, alebo je pauza kratsia nez PAUZA_DO_NAVRATU. Stop alebo koniec
playlistu vrati povodne pozadie po kratkom odklade (STOP_DO_NAVRATU) —
medzi dvoma skladbami prehravac na okamih zastavi a pozadie nema blikat.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from music_player.config_loader import load_config, set_value
from music_player.pozadie_plochy import Album, PozadiePlochy, farby_z_obalu, kluc_albumu

PAUZA_DO_NAVRATU_MS = 5 * 60 * 1000
STOP_DO_NAVRATU_MS = 15 * 1000
# Okienko medii vo Windows si cas posuva samo; staci mu ho obcas pripomenut.
CAS_DO_WINDOWS_S = 5.0

_WM_ENDSESSION = 0x0016

KLUC_POZADIE = "POZADIE_PLOCHY"
KLUC_MEDIA = "OVLADANIE_MEDII"
KLUC_PANEL = "PANEL_ULOH"


def _ano(hodnota: str | None, predvolene: bool = True) -> bool:
    if hodnota is None or not str(hodnota).strip():
        return predvolene
    return str(hodnota).strip().lower() not in {"nie", "no", "0", "false", "vypnute"}


def _typ_obrazka(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class WindowsIntegracia(QObject):
    """Jedna instancia na appku. Vytvara sa v app.py po okne."""

    # Okno nastaveni sa obnovi, ked sa zmeni stav niektorej casti.
    zmena = Signal()
    _kniznica_hotova = Signal(bool, str)

    def __init__(self, controller, okno) -> None:
        super().__init__(okno)
        self.controller = controller
        self.okno = okno
        cfg = load_config()
        self.pozadie_zapnute = _ano(cfg.get(KLUC_POZADIE))
        self.media_zapnute = _ano(cfg.get(KLUC_MEDIA))
        self.panel_zapnuty = _ano(cfg.get(KLUC_PANEL))

        self._zamok = threading.Lock()
        self._obal: bytes | None = None
        self._obal_verzia = ""
        self._farby: dict[str, str] | None = None
        self._obal_cesta = ""        # skladba, ku ktorej obal patri
        self._album_aktivny = False
        self._posledny_cas = 0.0
        self._posledna_pozicia = 0
        self.kniznica_stav = ""

        self.pozadie = PozadiePlochy()
        self.media = None
        self.panel = None

        self._navrat = QTimer(self)
        self._navrat.setSingleShot(True)
        self._navrat.timeout.connect(self._album_skoncil)
        self._kniznica_hotova.connect(self._po_instalacii)

    # -- start a koniec ----------------------------------------------------------
    def spusti(self) -> None:
        # Vlakno pozadia bezi vzdy, aj ked je funkcia vypnuta: po pade appky
        # musi vratit povodne pozadie, nech je dnes zapnuta alebo nie.
        self.pozadie.spusti()

        if self.panel_zapnuty:
            try:
                from music_player.panel_uloh import PanelUloh
                self.panel = PanelUloh(self.okno, self)
                self.panel.akcia.connect(self._na_akciu_panela)
            except Exception as exc:
                self.panel = None
                self._panel_chyba = str(exc)

        if self.media_zapnute:
            self._spusti_media()

        c = self.controller
        c.current_track_changed.connect(self._na_skladbu)
        c.playback_state_changed.connect(self._na_stav)
        c.position_changed.connect(self._na_poziciu)
        c.duration_changed.connect(lambda _d: self._na_poziciu(int(c.player.position()), vynutit=True))
        self.okno.obal_zobrazeny.connect(self._na_obal)

        self._na_skladbu(c.current_track())
        # Obal, ktory okno stihlo nacitat skor, nez sa integracia napojila.
        posledny = getattr(self.okno, "obal_posledny", None)
        if posledny:
            self._na_obal(*posledny)
        self._na_stav(c.playback_state_name())

    def zastav(self) -> None:
        """Pri ukonceni appky: povodne pozadie spat, okienko medii prec."""
        self._navrat.stop()
        self.pozadie.zastav(pockaj=4.0)
        if self.media is not None:
            self.media.zastav()
        if self.panel is not None:
            self.panel.zastav()

    def nativna_sprava(self, sprava) -> None:
        """Kazda sprava hlavneho okna (MainWindow.nativeEvent)."""
        if self.panel is not None:
            self.panel.nativna_sprava(sprava)
        # Vypnutie PC (aj to po dohrati playlistu): pozadie vratit hned.
        # Na aboutToQuit sa spoliehat neda — Windows appku pri vypinani
        # moze ukoncit skor, nez sa k nemu dostane.
        if ctypes.c_uint.from_address(int(sprava) + ctypes.sizeof(ctypes.c_void_p)).value == _WM_ENDSESSION:
            if ctypes.wintypes.MSG.from_address(int(sprava)).wParam:
                self.pozadie.vrat(pockaj=3.0)

    # -- ovladanie medii a kniznica ------------------------------------------------
    def _spusti_media(self) -> None:
        from music_player import kniznice
        if self.media is None:
            from music_player.windows_media import WindowsMedia
            self.media = WindowsMedia(self)
            self.media.tlacidlo.connect(self._na_tlacidlo_medii)
            self.media.posun.connect(self.controller.seek)
        if kniznice.chybaju():
            self.kniznica_stav = "inštalujem knižnicu winrt…"

            def instaluj() -> None:
                ok, chyba = kniznice.nainstaluj()
                self._kniznica_hotova.emit(ok, chyba)

            threading.Thread(target=instaluj, daemon=True, name="kniznica-winrt").start()
            return
        self._zapni_media()

    def _po_instalacii(self, ok: bool, chyba: str) -> None:
        if ok:
            self.kniznica_stav = "knižnica winrt doinštalovaná"
            if self.media_zapnute:
                self._zapni_media()
        else:
            self.kniznica_stav = f"knižnicu winrt sa nepodarilo nainštalovať: {chyba}"
        self.zmena.emit()

    def _zapni_media(self) -> None:
        if self.media is None:
            return
        self.media.spusti()
        track = self.controller.current_track()
        if track is not None:
            self.media.skladba(track.title, track.artist, track.album)
        with self._zamok:
            obal = self._obal
        if obal:
            self.media.obal(obal)
        self.media.stav_prehravania(self.controller.playback_state_name())
        self._na_poziciu(int(self.controller.player.position()), vynutit=True)
        QTimer.singleShot(1500, self.zmena.emit)

    def _na_tlacidlo_medii(self, akcia: str) -> None:
        stav = self.controller.playback_state_name()
        if akcia == "play" and stav != "playing" or akcia == "pause" and stav == "playing":
            # To iste ako tlacidlo v okne — aj s ulozenim stavu.
            self.okno._toggle_playback_from_ui()
        elif akcia == "stop":
            self.controller.stop()
        elif akcia == "next":
            self.controller.next_track()
        elif akcia == "prev":
            self.controller.previous_track()

    def _na_akciu_panela(self, akcia: str) -> None:
        if akcia == "playpause":
            self.okno._toggle_playback_from_ui()
        elif akcia == "next":
            self.controller.next_track()
        elif akcia == "prev":
            self.controller.previous_track()

    # -- signaly prehravaca ------------------------------------------------------------
    def _na_skladbu(self, track) -> None:
        if track is None:
            if self.media is not None:
                self.media.skladba("", "", "")
            if self.panel is not None:
                self.panel.popis("")
            return
        if self.media is not None:
            self.media.skladba(track.title, track.artist, track.album)
        if self.panel is not None:
            self.panel.popis(f"{track.artist} – {track.title}" if track.artist else track.title)
        self._posledny_cas = 0.0

    def _na_obal(self, cesta: str, data) -> None:
        track = self.controller.current_track()
        if track is None or track.path != cesta:
            return
        data = bytes(data) if data else None
        farby = farby_z_obalu(data) if data else None
        with self._zamok:
            zmena = data != self._obal
            self._obal = data
            self._obal_verzia = hashlib.sha1(data).hexdigest()[:12] if data else ""
            self._farby = farby
            self._obal_cesta = cesta
        if zmena and self.media is not None:
            self.media.obal(data)
        self._aktualizuj_album()

    def _na_stav(self, stav: str) -> None:
        if self.media is not None:
            self.media.stav_prehravania(stav)
        if self.panel is not None:
            self.panel.stav_prehravania(stav)
        self._na_poziciu(int(self.controller.player.position()), vynutit=True)
        self._aktualizuj_album()

    def _na_poziciu(self, pozicia: int, vynutit: bool = False) -> None:
        dlzka = int(self.controller.player.duration())
        if self.panel is not None:
            self.panel.cas(pozicia, dlzka)
        if self.media is None:
            return
        teraz = time.monotonic()
        # Skok (posun v skladbe) sa posle hned, inak raz za par sekund.
        ocakavana = self._posledna_pozicia + int((teraz - self._posledny_cas) * 1000)
        skok = abs(pozicia - ocakavana) > 2500
        if vynutit or skok or teraz - self._posledny_cas >= CAS_DO_WINDOWS_S:
            self._posledny_cas = teraz
            self._posledna_pozicia = pozicia
            self.media.cas(pozicia, dlzka)

    # -- album na ploche a vo Firefoxe ---------------------------------------------------
    def _aktualizuj_album(self) -> None:
        stav = self.controller.playback_state_name()
        if stav == "playing":
            self._navrat.stop()
            self._ukaz_album()
            return
        if not self._album_aktivny:
            return
        odklad = PAUZA_DO_NAVRATU_MS if stav == "paused" else STOP_DO_NAVRATU_MS
        # Uz bezi odpocet? Kratsi vyhra: stop po pauze nema cakat 5 minut.
        if self._navrat.isActive() and self._navrat.remainingTime() <= odklad:
            return
        self._navrat.start(odklad)

    def _ukaz_album(self) -> None:
        track = self.controller.current_track()
        with self._zamok:
            if track is None or self._obal_cesta != track.path:
                # Obal novej skladby este len pride (z pamate hned, z Metal
                # Archives o par sekund). Dovtedy ostava predosly — pri dalsej
                # skladbe toho isteho albumu by inak pozadie zablikalo.
                return
            obal = self._obal
            farby = self._farby
            self._album_aktivny = obal is not None
        if not self.pozadie_zapnute:
            return
        if obal is None:
            # Skladba bez obalu — radsej povodne pozadie nez obal ineho albumu.
            if self.pozadie.aktivne:
                self.pozadie.vrat()
            return
        self.pozadie.ukaz(Album(
            kluc=kluc_albumu(track.artist, track.album, obal),
            obal=obal,
            interpret=track.artist,
            album=track.album,
            rok=track.year,
            farby=farby,
        ))
        QTimer.singleShot(1500, self.zmena.emit)

    def _album_skoncil(self) -> None:
        with self._zamok:
            self._album_aktivny = False
        self.pozadie.vrat()
        QTimer.singleShot(1500, self.zmena.emit)

    # -- nastavenia z okna -----------------------------------------------------------------
    def nastav_pozadie(self, zapnute: bool) -> None:
        self.pozadie_zapnute = zapnute
        set_value(KLUC_POZADIE, "ano" if zapnute else "nie")
        if zapnute:
            self._aktualizuj_album()
        else:
            self.pozadie.vrat()
        QTimer.singleShot(1500, self.zmena.emit)

    def nastav_media(self, zapnute: bool) -> None:
        self.media_zapnute = zapnute
        set_value(KLUC_MEDIA, "ano" if zapnute else "nie")
        if zapnute:
            self._spusti_media()
        elif self.media is not None:
            self.media.zastav()
        QTimer.singleShot(1500, self.zmena.emit)

    def nastav_panel(self, zapnuty: bool) -> None:
        # Tlacidla v nahlade sa za behu odobrat nedaju (Windows na to nema
        # volanie) — zmena plati od dalsieho spustenia.
        self.panel_zapnuty = zapnuty
        set_value(KLUC_PANEL, "ano" if zapnuty else "nie")

    # -- pre API (vola sa z vlakna HTTP servera) ---------------------------------------------
    def api_polia(self) -> dict:
        """Polia navyse do /api/now-playing.

        Obal a farby su vzdy tie posledne zname — kym obal novej skladby
        nepride, ostava predosly. Firefox sa pyta kazde 2 s a bez toho by pri
        kazdej skladbe na okamih stratil temu.
        """
        track = self.controller.current_track()
        with self._zamok:
            return {
                "album": track.album if track else "",
                "year": track.year if track else "",
                "obalVerzia": self._obal_verzia,
                "farby": dict(self._farby) if self._farby else None,
                "albumAktivny": bool(self._album_aktivny and self._obal),
            }

    def obal_pre_api(self) -> tuple[bytes, str] | None:
        with self._zamok:
            if not self._obal:
                return None
            return self._obal, _typ_obrazka(self._obal)

    def stav_pre_api(self) -> dict:
        return {
            "pozadie": self.pozadie.stav if self.pozadie_zapnute else "vypnuté",
            "ovladanieMedii": (self.media.stav if self.media is not None else self.kniznica_stav or "vypnuté")
            if self.media_zapnute else "vypnuté",
            "kniznica": self.kniznica_stav,
            "panelUloh": (self.panel.stav if self.panel is not None else "vypnuté"),
            "farbaStartu": farba_startu_popis(),
        }


# ── farba Startu a panela uloh (len citanie) ───────────────────────────────────
def farba_startu() -> dict:
    """Ako ma Windows nastavene farby. Prehravac ich nemeni — len radi."""
    import winreg

    def citaj(kluc: str, hodnota: str):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kluc) as k:
                return winreg.QueryValueEx(k, hodnota)[0]
        except OSError:
            return None

    return {
        "automaticka": citaj(r"Control Panel\Desktop", "AutoColorization") == 1,
        "naStarte": citaj(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                          "ColorPrevalence") == 1,
        "tmavy": citaj(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                       "SystemUsesLightTheme") == 0,
    }


def farba_startu_popis() -> str:
    f = farba_startu()
    if f["automaticka"] and f["naStarte"] and f["tmavy"]:
        return "Štart a panel úloh sa farbia podľa albumu"
    if f["automaticka"]:
        return "farba zvýraznenia ide podľa pozadia, na Štarte a paneli úloh sa ale neukazuje"
    return "farba zvýraznenia je nastavená ručne — Štart a panel úloh sa podľa albumu nemenia"
