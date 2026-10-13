"""Mys a klavesnica na dialku — telefon ako touchpad.

Telefon otvori na API porte jedno trvale spojenie (``POST /api/mouse``) a
posiela nim riadky, jeden prikaz na riadok:

    m <dx> <dy>     posun kurzora o dx, dy (relativne, v bodoch)
    c <l|r|m>       klik
    d <l|r|m>       tlacidlo dole (zaciatok tahania)
    u <l|r|m>       tlacidlo hore
    s <n>           koliesko zvisle, n v jednotkach Windows (120 = jeden zub,
                    kladne = hore)
    h <n>           koliesko vodorovne (kladne = doprava)
    t <text>        napise text (Unicode, nezavisle od rozlozenia klavesnice)
    k <kombinacia>  kláves, napr. ``enter``, ``ctrl+c``, ``alt+f4``, ``win``
    p               nic — len udrzanie spojenia

Pohyby idu cez to iste TCP spojenie ako kliky: su v spravnom poradi a klik
sa nestrati. UDP by znamenalo novu vynimku vo firewalle na oboch notebookoch
(``oprava-lan-pristupu.cmd`` povoluje len TCP 8765) a klik, ktory Wi-Fi
zahodi, by sa tvaril ako nefunkcne tuknutie.

Kurzor sa hybe cez ``SendInput``, rovnako ako skutocna mys — Windows k nemu
prida vlastne zrychlenie ("Zvysit presnost ukazovatela"). Okna spustene ako
spravca, UAC ani zamknuta obrazovka sa takto ovladat nedaju (UIPI); to je
obmedzenie Windowsu, nie tejto appky.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from typing import Callable

_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_MIDDLEDOWN = 0x0020
_MOUSEEVENTF_MIDDLEUP = 0x0040
_MOUSEEVENTF_WHEEL = 0x0800
_MOUSEEVENTF_HWHEEL = 0x1000

_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

_TLACIDLA = {
    "l": (_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP),
    "r": (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP),
    "m": (_MOUSEEVENTF_MIDDLEDOWN, _MOUSEEVENTF_MIDDLEUP),
}

# Virtualne klavesy. Rozsirene (extended) su tie, ktore na klavesnici existuju
# dvakrat alebo mimo numerickej casti — bez priznaku by sipky v niektorych
# appkach posielali cisla z numerickej klavesnice.
_KLAVESY: dict[str, int] = {
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4, "win": 0x5B,
    "printscreen": 0x2C, "menu": 0x5D,
    "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD,
}
_KLAVESY.update({f"f{i}": 0x6F + i for i in range(1, 13)})
_KLAVESY.update({chr(c): c for c in range(ord("0"), ord("9") + 1)})
_KLAVESY.update({chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)})
_ROZSIRENE = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28,
              0x5B, 0x5D, 0x2C, 0xAF, 0xAE, 0xAD}

# Jeden prikaz nesmie pohnut kurzorom cez pol vesmiru — chybny riadok
# (alebo prehnane zrychlenie v telefone) sa oreze.
_MAX_POSUN = 2000
_MAX_KOLIESKO = 120 * 20
_MAX_TEXT = 2000


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD), ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def _mys(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> _INPUT:
    vstup = _INPUT(type=_INPUT_MOUSE)
    # mouseData je DWORD, koliesko nadol je vsak zaporne cislo.
    vstup.u.mi = _MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return vstup


def _klaves(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    vstup = _INPUT(type=_INPUT_KEYBOARD)
    vstup.u.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    return vstup


def _send_input(vstupy: list[_INPUT]) -> None:
    if not vstupy or sys.platform != "win32":
        return
    pole = (_INPUT * len(vstupy))(*vstupy)
    ctypes.windll.user32.SendInput(len(vstupy), pole, ctypes.sizeof(_INPUT))


def _cele(text: str, limit: int) -> int:
    return max(-limit, min(limit, int(float(text))))


class DialkovaMys:
    """Vykonava riadky protokolu (viz. hlavicka modulu).

    ``posli`` sa da v testoch nahradit — dostane zoznam ``_INPUT`` struktur,
    ktore by inak isli do ``SendInput``.
    """

    def __init__(self, posli: Callable[[list[_INPUT]], None] = _send_input) -> None:
        self._posli = posli
        self._drzane: set[str] = set()

    def vykonaj(self, riadok: str) -> bool:
        """Vykona jeden riadok. False = neznamy alebo chybny prikaz (ignoruje sa)."""
        prikaz, _, zvysok = riadok.partition(" ")
        try:
            if prikaz == "m":
                dx, dy = zvysok.split()
                self._posli([_mys(_MOUSEEVENTF_MOVE,
                                  _cele(dx, _MAX_POSUN), _cele(dy, _MAX_POSUN))])
            elif prikaz in ("c", "d", "u"):
                dole, hore = _TLACIDLA[zvysok.strip()]
                tl = zvysok.strip()
                if prikaz == "c":
                    self._posli([_mys(dole), _mys(hore)])
                    self._drzane.discard(tl)
                elif prikaz == "d":
                    self._posli([_mys(dole)])
                    self._drzane.add(tl)
                else:
                    self._posli([_mys(hore)])
                    self._drzane.discard(tl)
            elif prikaz == "s":
                self._posli([_mys(_MOUSEEVENTF_WHEEL,
                                  data=_cele(zvysok, _MAX_KOLIESKO))])
            elif prikaz == "h":
                self._posli([_mys(_MOUSEEVENTF_HWHEEL,
                                  data=_cele(zvysok, _MAX_KOLIESKO))])
            elif prikaz == "t":
                self._posli(_text(zvysok[:_MAX_TEXT]))
            elif prikaz == "k":
                vstupy = _kombinacia(zvysok.strip().lower())
                if vstupy is None:
                    return False
                self._posli(vstupy)
            elif prikaz == "p":
                pass
            else:
                return False
        except (ValueError, KeyError):
            return False
        return True

    def uvolni(self) -> None:
        """Pusti drzane tlacidla — ked spojenie padne uprostred tahania,
        lave tlacidlo nesmie ostat na PC stlacene."""
        for tl in sorted(self._drzane):
            self._posli([_mys(_TLACIDLA[tl][1])])
        self._drzane.clear()


def _text(text: str) -> list[_INPUT]:
    vstupy: list[_INPUT] = []
    for znak in text:
        if znak == "\n":
            vstupy += [_klaves(0x0D), _klaves(0x0D, flags=_KEYEVENTF_KEYUP)]
            continue
        # Znaky mimo BMP (emoji) su v UTF-16 dve jednotky — kazda ide zvlast.
        kod = znak.encode("utf-16-le")
        for i in range(0, len(kod), 2):
            jednotka = int.from_bytes(kod[i:i + 2], "little")
            vstupy.append(_klaves(scan=jednotka, flags=_KEYEVENTF_UNICODE))
            vstupy.append(_klaves(scan=jednotka,
                                  flags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
    return vstupy


def _kombinacia(kombinacia: str) -> list[_INPUT] | None:
    casti = [c for c in kombinacia.split("+") if c]
    if not casti or any(c not in _KLAVESY for c in casti):
        return None
    vk = [_KLAVESY[c] for c in casti]

    def flags(kod: int) -> int:
        return _KEYEVENTF_EXTENDEDKEY if kod in _ROZSIRENE else 0

    dole = [_klaves(k, flags=flags(k)) for k in vk]
    hore = [_klaves(k, flags=flags(k) | _KEYEVENTF_KEYUP) for k in reversed(vk)]
    return dole + hore
