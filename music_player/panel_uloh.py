"""Tlacidla ⏮ ⏯ ⏭ v nahlade na paneli uloh a priebeh skladby v ikone.

Ked okno prehravaca nie je schovane v lište vedla hodin, ma na paneli uloh
ikonu. Po prejdeni mysou nad nu ukaze Windows nahlad okna a pod nim tieto
tri tlacidla; samotna ikona sa pocas hrania plni zelenym pasom (pri pauze
zltym), ako pri kopirovani suborov.

Qt 5 to vedelo cez QtWinExtras, Qt 6 uz nie — preto priamo ITaskbarList3
cez ctypes. Kliky na tlacidla chodia oknu ako WM_COMMAND. Zachytit ich treba
v `nativeEvent` samotneho okna (`MainWindow.nativeEvent` vola
`nativna_sprava`): filter nativnych sprav celej appky
(`QAbstractNativeEventFilter`) vidi len spravy z fronty, nie poslane cez
SendMessage — overene 1. 11. 2026, poslany WM_COMMAND do filtra nedosiel.

Tlacidla sa daju pridat az ked Windows ikonu na paneli vytvori (sprava
"TaskbarButtonCreated") — a znova po kazdom schovani a ukazani okna, lebo
vtedy ikona zanikne a vznikne nova.
"""
from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_long, c_uint, c_ulonglong, c_void_p, wintypes

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

_user32 = ctypes.windll.user32  # type: ignore[attr-defined]
_ole32 = ctypes.windll.ole32    # type: ignore[attr-defined]

_WM_COMMAND = 0x0111
_THBN_CLICKED = 0x1800
_THB_ICON = 0x2
_THB_TOOLTIP = 0x4
_THB_FLAGS = 0x8
_THBF_ENABLED = 0x0

_TBPF_NOPROGRESS = 0x0
_TBPF_NORMAL = 0x2
_TBPF_PAUSED = 0x8

_ID_PREV, _ID_PLAY, _ID_NEXT = 1, 2, 3
_AKCIE = {_ID_PREV: "prev", _ID_PLAY: "playpause", _ID_NEXT: "next"}


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    g = _GUID()
    _ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(g))
    return g


class _THUMBBUTTON(ctypes.Structure):
    _fields_ = [
        ("dwMask", wintypes.DWORD),
        ("iId", c_uint),
        ("iBitmap", c_uint),
        ("hIcon", wintypes.HICON),
        ("szTip", ctypes.c_wchar * 260),
        ("dwFlags", wintypes.DWORD),
    ]


class _TaskbarList3:
    """ITaskbarList3 (shobjidl_core.h). Poradie vo vtable: 0-2 IUnknown,
    3 HrInit, 4 AddTab, 5 DeleteTab, 6 ActivateTab, 7 SetActiveAlt,
    8 MarkFullscreenWindow, 9 SetProgressValue, 10 SetProgressState,
    11 RegisterTab, 12 UnregisterTab, 13 SetTabOrder, 14 SetTabActive,
    15 ThumbBarAddButtons, 16 ThumbBarUpdateButtons, 17 ThumbBarSetImageList,
    18 SetOverlayIcon, 19 SetThumbnailTooltip, 20 SetThumbnailClip."""

    def __init__(self) -> None:
        ptr = c_void_p()
        hr = _ole32.CoCreateInstance(
            byref(_guid("{56FDF344-FD6D-11d0-958A-006097C9A090}")), None, 0x1,
            byref(_guid("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")), byref(ptr),
        )
        if hr < 0 or not ptr.value:
            raise OSError(f"ITaskbarList3: 0x{hr & 0xFFFFFFFF:08X}")
        self._ptr = ptr
        self._volaj(3, ())

    def _volaj(self, index: int, argtypes: tuple, *args) -> int:
        vtable = ctypes.cast(self._ptr, POINTER(POINTER(c_void_p))).contents
        hr = ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtable[index])(self._ptr, *args)
        if hr < 0:
            raise OSError(f"ITaskbarList3[{index}]: 0x{hr & 0xFFFFFFFF:08X}")
        return hr

    def priebeh(self, hwnd: int, hotovo: int, celkom: int) -> None:
        self._volaj(9, (wintypes.HWND, c_ulonglong, c_ulonglong), hwnd, hotovo, celkom)

    def stav_priebehu(self, hwnd: int, stav: int) -> None:
        self._volaj(10, (wintypes.HWND, ctypes.c_int), hwnd, stav)

    def pridaj_tlacidla(self, hwnd: int, tlacidla) -> None:
        self._volaj(15, (wintypes.HWND, c_uint, POINTER(_THUMBBUTTON)), hwnd, len(tlacidla), tlacidla)

    def zmen_tlacidla(self, hwnd: int, tlacidla) -> None:
        self._volaj(16, (wintypes.HWND, c_uint, POINTER(_THUMBBUTTON)), hwnd, len(tlacidla), tlacidla)

    def popis_nahladu(self, hwnd: int, text: str) -> None:
        self._volaj(19, (wintypes.HWND, ctypes.c_wchar_p), hwnd, text)


# ── ikony ─────────────────────────────────────────────────────────────────────
def _ikona(tvar: str, velkost: int) -> int:
    """Biela ikona ⏮ ▶ ⏸ ⏭ ako HICON. Kreslena, aby nezavisela od pisma."""
    img = QImage(velkost, velkost, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    s = velkost
    m = s * 0.18

    def trojuholnik(x0: float, x1: float, doprava: bool) -> None:
        cesta = QPainterPath()
        if doprava:
            cesta.moveTo(QPointF(x0, m))
            cesta.lineTo(QPointF(x1, s / 2))
            cesta.lineTo(QPointF(x0, s - m))
        else:
            cesta.moveTo(QPointF(x1, m))
            cesta.lineTo(QPointF(x0, s / 2))
            cesta.lineTo(QPointF(x1, s - m))
        cesta.closeSubpath()
        p.drawPath(cesta)

    pruh = max(s * 0.12, 1.5)
    if tvar == "play":
        trojuholnik(s * 0.28, s * 0.80, True)
    elif tvar == "pause":
        p.drawRect(int(s * 0.26), int(m), int(s * 0.17), int(s - 2 * m))
        p.drawRect(int(s * 0.57), int(m), int(s * 0.17), int(s - 2 * m))
    elif tvar == "next":
        trojuholnik(s * 0.18, s * 0.70, True)
        p.drawRect(int(s * 0.70), int(m), int(pruh), int(s - 2 * m))
    elif tvar == "prev":
        trojuholnik(s * 0.30, s * 0.82, False)
        p.drawRect(int(s * 0.30 - pruh), int(m), int(pruh), int(s - 2 * m))
    p.end()
    return int(img.toHICON())


class PanelUloh(QObject):
    """Tlacidla v nahlade a priebeh v ikone pre jedno okno."""

    akcia = Signal(str)   # "prev" | "playpause" | "next"

    def __init__(self, okno, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._okno = okno
        self._sprava_vytvorena = _user32.RegisterWindowMessageW("TaskbarButtonCreated")
        self._panel: _TaskbarList3 | None = None
        self._tlacidla_pridane_pre = 0
        self._hra = False
        self._stav_priebehu = _TBPF_NOPROGRESS
        self._posledny_podiel = -1
        self._popis = ""
        self.stav = "čaká na okno"
        velkost = max(int(_user32.GetSystemMetrics(49)), 16)  # SM_CXSMICON
        self._ikony = {t: _ikona(t, velkost) for t in ("prev", "play", "pause", "next")}

    # -- z appky ---------------------------------------------------------------
    def stav_prehravania(self, stav: str) -> None:
        hra = stav == "playing"
        zmena = hra != self._hra
        self._hra = hra
        if zmena and self._tlacidla_pridane_pre:
            self._uprav_tlacidla(zmen=True)
        novy = {"playing": _TBPF_NORMAL, "paused": _TBPF_PAUSED}.get(stav, _TBPF_NOPROGRESS)
        if novy != self._stav_priebehu:
            self._stav_priebehu = novy
            self._posledny_podiel = -1
            self._nastav_priebeh_stav()

    def cas(self, pozicia_ms: int, dlzka_ms: int) -> None:
        if self._panel is None or self._stav_priebehu == _TBPF_NOPROGRESS or dlzka_ms <= 0:
            return
        podiel = int(min(max(pozicia_ms, 0), dlzka_ms) * 1000 // dlzka_ms)
        if podiel == self._posledny_podiel:
            return
        self._posledny_podiel = podiel
        try:
            self._panel.priebeh(self._hwnd(), podiel, 1000)
        except OSError:
            pass

    def popis(self, text: str) -> None:
        """Bublina nad nahladom okna — co hra."""
        self._popis = text
        if self._panel is not None:
            try:
                self._panel.popis_nahladu(self._hwnd(), text or "Metal Music Player")
            except OSError:
                pass

    def zastav(self) -> None:
        for hicon in self._ikony.values():
            _user32.DestroyIcon(wintypes.HICON(hicon))
        self._ikony = {}

    # -- nativne spravy ----------------------------------------------------------
    def _hwnd(self) -> int:
        return int(self._okno.winId())

    def nativna_sprava(self, sprava) -> None:
        """Volane z `nativeEvent` okna pre kazdu jeho spravu — musi byt rychle."""
        msg = wintypes.MSG.from_address(int(sprava))
        if msg.message == self._sprava_vytvorena or msg.message == _WM_COMMAND:
            self._sprava(msg)

    def _sprava(self, msg: wintypes.MSG) -> None:
        if not self._ikony:
            return
        if msg.message == self._sprava_vytvorena:
            if int(msg.hWnd or 0) == self._hwnd():
                self._ikona_vytvorena()
        elif msg.message == _WM_COMMAND:
            w = int(msg.wParam or 0)
            if (w >> 16) & 0xFFFF == _THBN_CLICKED and int(msg.hWnd or 0) == self._hwnd():
                akcia = _AKCIE.get(w & 0xFFFF)
                if akcia:
                    self.akcia.emit(akcia)

    def _ikona_vytvorena(self) -> None:
        try:
            if self._panel is None:
                self._panel = _TaskbarList3()
            self._uprav_tlacidla(zmen=False)
            self._tlacidla_pridane_pre = self._hwnd()
            self._posledny_podiel = -1
            self._nastav_priebeh_stav()
            if self._popis:
                self._panel.popis_nahladu(self._hwnd(), self._popis)
            self.stav = "zapnuté"
        except OSError as exc:
            self.stav = f"chyba: {exc}"

    def _uprav_tlacidla(self, *, zmen: bool) -> None:
        if self._panel is None:
            return
        pole = (_THUMBBUTTON * 3)()
        for i, (ident, ikona, tip) in enumerate((
            (_ID_PREV, "prev", "Predošlá"),
            (_ID_PLAY, "pause" if self._hra else "play", "Pauza" if self._hra else "Hrať"),
            (_ID_NEXT, "next", "Ďalšia"),
        )):
            pole[i].dwMask = _THB_ICON | _THB_TOOLTIP | _THB_FLAGS
            pole[i].iId = ident
            pole[i].hIcon = self._ikony[ikona]
            pole[i].szTip = tip
            pole[i].dwFlags = _THBF_ENABLED
        try:
            if zmen:
                self._panel.zmen_tlacidla(self._hwnd(), pole)
            else:
                self._panel.pridaj_tlacidla(self._hwnd(), pole)
        except OSError as exc:
            self.stav = f"chyba tlačidiel: {exc}"

    def _nastav_priebeh_stav(self) -> None:
        if self._panel is None:
            return
        try:
            self._panel.stav_priebehu(self._hwnd(), self._stav_priebehu)
        except OSError:
            pass
