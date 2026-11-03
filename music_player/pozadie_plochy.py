"""Pozadie plochy podla prave hrajuceho albumu.

Ked hra hudba, plocha ukazuje obal albumu: rozmazany a stmaveny obal cez celu
obrazovku, v strede ostry obal a pod nim interpret, album a rok. Ked hudba
stoji (stop, dlha pauza, koniec appky), vrati sa povodne pozadie.

Windows z toho vie odvodit aj farbu Startu a panela uloh — staci, ked ma
clovek v Nastaveniach -> Prisposobenie -> Farby zapnutu automaticku farbu
zvyraznenia. Appka systemove prepinace sama nemeni.

Tri veci, na ktorych to stoji:

* **Povodne pozadie sa nesmie stratit.** Pred prvou zmenou sa zapise do
  `%APPDATA%\\LanMusicPlayer\\pozadie\\povodne.json` (cesta pre kazdy monitor,
  sposob vyplnenia, zoznam poslednych obrazkov v Nastaveniach) a obrazok sa
  skopiruje vedla — keby ho clovek medzicasom zmazal, vrati sa kopia. Ked
  appka spadne alebo ju zabije vypnutie PC, ten subor ostane a pri dalsom
  spusteni sa pozadie vrati z neho.
* **Pozadie, ktore si clovek medzicasom zmenil sam, sa neprepisuje spat.**
  Vracia sa len vtedy, ked na ploche je este obrazok od prehravaca.
* **Prezentacia ani Windows Spotlight sa nemenia.** Tie sa z programu neda
  spolahlivo vratit, takze prehravac vtedy pozadie nechava tak a povie preco.

Cele to bezi vo vlastnom vlakne: skladanie obrazka trva desatiny sekundy
a nastavenie pozadia je volanie do Prieskumnika, ktore obcas chvilu trva.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import queue
import shutil
import threading
import winreg
from ctypes import POINTER, byref, c_long, c_uint, c_void_p, wintypes
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)


def predvoleny_priecinok() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "LanMusicPlayer" / "pozadie"


# ── farby z obalu ─────────────────────────────────────────────────────────────
def _hex(c: QColor) -> str:
    return c.name(QColor.NameFormat.HexRgb)


def farby_z_obalu(data: bytes | None) -> dict[str, str] | None:
    """Tri farby z obalu: tmave pozadie, vyrazny akcent a citatelny text.

    Pouziva ich obrazok na plochu aj tema Firefoxu, takze sa oba zhodnu.
    Akcent je najsytejsi casty odtien — priemer celeho obalu by u metalu
    skoro vzdy vysiel ako blatisto hneda. Ciernobiely obal (black metal)
    dostane namiesto akcentu svetlosivu.
    """
    if not data:
        return None
    img = QImage()
    if not img.loadFromData(data) or img.isNull():
        return None
    male = img.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
    koše: dict[int, list[float]] = {}
    sucet = [0.0, 0.0, 0.0]
    pocet = 0
    for y in range(male.height()):
        for x in range(male.width()):
            c = male.pixelColor(x, y)
            sucet[0] += c.red()
            sucet[1] += c.green()
            sucet[2] += c.blue()
            pocet += 1
            h, s, v = c.hsvHueF(), c.hsvSaturationF(), c.valueF()
            if h < 0 or s < 0.25 or v < 0.2:
                continue
            vaha = s * v
            kos = koše.setdefault(int(h * 24) % 24, [0.0, 0.0, 0.0, 0.0])
            kos[0] += vaha
            kos[1] += c.red() * vaha
            kos[2] += c.green() * vaha
            kos[3] += c.blue() * vaha
    if not pocet:
        return None
    priemer = QColor(int(sucet[0] / pocet), int(sucet[1] / pocet), int(sucet[2] / pocet))

    najlepsi = max(koše.values(), key=lambda k: k[0], default=None)
    # Prah: aspon zopar sytych pixelov, inak je akcent nahodny sum.
    if najlepsi is not None and najlepsi[0] >= 6.0:
        akcent = QColor(int(najlepsi[1] / najlepsi[0]), int(najlepsi[2] / najlepsi[0]),
                        int(najlepsi[3] / najlepsi[0]))
        h, s, l = akcent.hslHueF(), akcent.hslSaturationF(), akcent.lightnessF()
        akcent = QColor.fromHslF(max(h, 0.0), min(1.0, max(s, 0.55)), min(0.62, max(l, 0.48)))
    else:
        akcent = QColor(200, 200, 200)

    ph = priemer.hslHueF()
    ps = priemer.hslSaturationF()
    ph = ph if ph >= 0 else 0.0
    pozadie = QColor.fromHslF(ph, min(ps, 0.45) * 0.8, 0.11)
    lista = QColor.fromHslF(ph, min(ps, 0.45) * 0.8, 0.17)
    text = QColor.fromHslF(max(akcent.hslHueF(), 0.0), 0.15, 0.93)
    return {
        "pozadie": _hex(pozadie),
        "lista": _hex(lista),
        "akcent": _hex(akcent),
        "text": _hex(text),
    }


# ── skladanie obrazka ─────────────────────────────────────────────────────────
def _rozmaz(img: QImage, sirka: int, vyska: int) -> QImage:
    """Obal roztiahnuty cez celu plochu a rozmazany.

    Skutocny Gaussov filter by na 1920x1080 v Pythone trval sekundy. Zmensenie
    na drobny obrazok a postupne zvacsovanie s vyhladzovanim da na pozadie ten
    isty dojem za zlomok casu.
    """
    vyplnene = img.scaled(sirka, vyska, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
    x = (vyplnene.width() - sirka) // 2
    y = (vyplnene.height() - vyska) // 2
    vyplnene = vyplnene.copy(x, y, sirka, vyska)
    male = vyplnene.scaled(max(sirka // 40, 8), max(vyska // 40, 8),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    stredne = male.scaled(max(sirka // 8, 16), max(vyska // 8, 16),
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    return stredne.scaled(sirka, vyska, Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)


def zloz_obrazok(
    data: bytes,
    sirka: int,
    vyska: int,
    *,
    interpret: str = "",
    album: str = "",
    rok: str = "",
    farby: dict[str, str] | None = None,
) -> QImage | None:
    """Obrazok na plochu presne na rozlisenie monitora. None = obal sa neda nacitat."""
    obal = QImage()
    if not obal.loadFromData(data) or obal.isNull() or sirka < 64 or vyska < 64:
        return None
    obal = obal.convertToFormat(QImage.Format.Format_RGB32)
    farby = farby or farby_z_obalu(data) or {}
    akcent = QColor(farby.get("akcent", "#c8c8c8"))

    vysledok = _rozmaz(obal, sirka, vyska).convertToFormat(QImage.Format.Format_RGB32)
    p = QPainter(vysledok)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Stmavenie: rovnomerne + vineta, aby ikony a text na ploche boli citatelne.
    p.fillRect(vysledok.rect(), QColor(0, 0, 0, 120))
    vineta = QRadialGradient(QPointF(sirka / 2, vyska * 0.45), max(sirka, vyska) * 0.75)
    vineta.setColorAt(0.0, QColor(0, 0, 0, 0))
    vineta.setColorAt(1.0, QColor(0, 0, 0, 150))
    p.fillRect(vysledok.rect(), vineta)

    # Ostry obal v strede, trochu nad stredom — dole je panel uloh.
    strana = int(min(vyska * 0.46, sirka * 0.34))
    riadky_vyska = vyska * 0.16
    blok = strana + riadky_vyska
    x0 = (sirka - strana) / 2
    y0 = max(vyska * 0.06, (vyska - blok) / 2 - vyska * 0.03)
    ramik = QRectF(x0, y0, strana, strana)

    # Mekky tien pod obalom.
    for i in range(14, 0, -1):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 9))
        p.drawRoundedRect(ramik.adjusted(-i * 1.6, -i * 0.8, i * 1.6, i * 2.6), 10 + i, 10 + i)
    cesta = QPainterPath()
    cesta.addRoundedRect(ramik, 8, 8)
    p.save()
    p.setClipPath(cesta)
    p.drawImage(ramik, obal.scaled(strana, strana, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation))
    p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 40), 1.2))
    p.drawPath(cesta)

    # Text pod obalom.
    y = ramik.bottom() + vyska * 0.035
    sirka_textu = sirka * 0.7

    def riadok(text: str, velkost: float, vaha: QFont.Weight, farba: QColor) -> None:
        nonlocal y
        if not text:
            return
        pismo = QFont("Segoe UI")
        pismo.setPixelSize(max(int(velkost), 10))
        pismo.setWeight(vaha)
        fm = QFontMetricsF(pismo)
        text = fm.elidedText(text, Qt.TextElideMode.ElideRight, sirka_textu)
        w = fm.horizontalAdvance(text)
        x = (sirka - w) / 2
        y_zakladna = y + fm.ascent()
        p.setFont(pismo)
        p.setPen(QColor(0, 0, 0, 140))
        p.drawText(QPointF(x + 1.5, y_zakladna + 2), text)
        p.setPen(farba)
        p.drawText(QPointF(x, y_zakladna), text)
        y += fm.height() * 1.05

    riadok(interpret, vyska * 0.042, QFont.Weight.DemiBold, QColor(245, 242, 238))
    riadok(album, vyska * 0.029, QFont.Weight.Normal, QColor(225, 220, 214))
    if rok:
        # Tenka ciara v akcente pod albumom, za nou rok.
        ciara = QLinearGradient(QPointF(sirka / 2 - strana * 0.25, 0), QPointF(sirka / 2 + strana * 0.25, 0))
        ciara.setColorAt(0.0, QColor(akcent.red(), akcent.green(), akcent.blue(), 0))
        ciara.setColorAt(0.5, akcent)
        ciara.setColorAt(1.0, QColor(akcent.red(), akcent.green(), akcent.blue(), 0))
        p.setPen(QPen(ciara, max(vyska * 0.002, 1.5)))
        y += vyska * 0.006
        p.drawLine(QPointF(sirka / 2 - strana * 0.25, y), QPointF(sirka / 2 + strana * 0.25, y))
        y += vyska * 0.012
        riadok(rok, vyska * 0.022, QFont.Weight.Light, QColor(200, 196, 190))
    p.end()
    return vysledok


# ── IDesktopWallpaper cez ctypes ──────────────────────────────────────────────
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


_ole32 = ctypes.windll.ole32 if os.name == "nt" else None  # type: ignore[attr-defined]


def _guid(text: str) -> _GUID:
    g = _GUID()
    hr = _ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(g))
    if hr < 0:
        raise OSError(f"CLSIDFromString {text}: 0x{hr & 0xFFFFFFFF:08X}")
    return g


_CLSID_DESKTOP_WALLPAPER = "{C2CF3110-460E-4fc1-B9D0-8A1C0C9CC4BD}"
_IID_IDESKTOP_WALLPAPER = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
_CLSCTX_ALL = 0x17
_COINIT_APARTMENTTHREADED = 0x2

# DESKTOP_WALLPAPER_POSITION
POZICIA_VYPLNIT = 4
# DESKTOP_SLIDESHOW_STATE
_DSS_SLIDESHOW = 0x2


class _DesktopWallpaper:
    """Tenky obal nad IDesktopWallpaper (shobjidl_core.h). Iba to, co treba.

    Poradie metod vo vtable: 0-2 IUnknown, 3 SetWallpaper, 4 GetWallpaper,
    5 GetMonitorDevicePathAt, 6 GetMonitorDevicePathCount, 7 GetMonitorRECT,
    8 SetBackgroundColor, 9 GetBackgroundColor, 10 SetPosition, 11 GetPosition,
    12 SetSlideshow, 13 GetSlideshow, 14 SetSlideshowOptions,
    15 GetSlideshowOptions, 16 AdvanceSlideshow, 17 GetStatus, 18 Enable.
    """

    def __init__(self) -> None:
        ptr = c_void_p()
        hr = _ole32.CoCreateInstance(
            byref(_guid(_CLSID_DESKTOP_WALLPAPER)), None, _CLSCTX_ALL,
            byref(_guid(_IID_IDESKTOP_WALLPAPER)), byref(ptr),
        )
        if hr < 0 or not ptr.value:
            raise OSError(f"IDesktopWallpaper sa nepodarilo vytvorit: 0x{hr & 0xFFFFFFFF:08X}")
        self._ptr = ptr

    def _volaj(self, index: int, argtypes: tuple, *args) -> int:
        vtable = ctypes.cast(self._ptr, POINTER(POINTER(c_void_p))).contents
        funkcia = ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtable[index])
        hr = funkcia(self._ptr, *args)
        if hr < 0:
            raise OSError(f"IDesktopWallpaper[{index}]: 0x{hr & 0xFFFFFFFF:08X}")
        return hr

    def _retazec_von(self, index: int, prvy_typ, prvy) -> str:
        von = c_void_p()
        self._volaj(index, (prvy_typ, POINTER(c_void_p)), prvy, byref(von))
        if not von.value:
            return ""
        try:
            return ctypes.wstring_at(von.value)
        finally:
            _ole32.CoTaskMemFree(von)

    def monitory(self) -> list[str]:
        pocet = c_uint()
        self._volaj(6, (POINTER(c_uint),), byref(pocet))
        return [self._retazec_von(5, c_uint, i) for i in range(pocet.value)]

    def obdlznik(self, monitor: str) -> tuple[int, int, int, int]:
        r = wintypes.RECT()
        self._volaj(7, (ctypes.c_wchar_p, POINTER(wintypes.RECT)), monitor, byref(r))
        return r.left, r.top, r.right, r.bottom

    def zapojene(self) -> list[tuple[str, int, int]]:
        """Monitory, ktore naozaj nieco ukazuju: (id, sirka, vyska).

        Zoznam z `monitory()` obsahuje aj odpojene a neaktivne (napr. displej
        vzdialenej plochy) — GetMonitorRECT na nich vrati E_FAIL.
        """
        vysledok = []
        for monitor in self.monitory():
            try:
                l, t, r, b = self.obdlznik(monitor)
            except OSError:
                continue
            if r - l > 0 and b - t > 0:
                vysledok.append((monitor, r - l, b - t))
        return vysledok

    def pozadie(self, monitor: str) -> str:
        return self._retazec_von(4, ctypes.c_wchar_p, monitor)

    def nastav(self, monitor: str | None, cesta: str) -> None:
        self._volaj(3, (ctypes.c_wchar_p, ctypes.c_wchar_p), monitor, cesta)

    def pozicia(self) -> int:
        h = ctypes.c_int()
        self._volaj(11, (POINTER(ctypes.c_int),), byref(h))
        return h.value

    def nastav_poziciu(self, pozicia: int) -> None:
        self._volaj(10, (ctypes.c_int,), pozicia)

    def stav(self) -> int:
        h = ctypes.c_int()
        self._volaj(17, (POINTER(ctypes.c_int),), byref(h))
        return h.value

    def uvolni(self) -> None:
        if self._ptr and self._ptr.value:
            vtable = ctypes.cast(self._ptr, POINTER(POINTER(c_void_p))).contents
            ctypes.WINFUNCTYPE(c_uint, c_void_p)(vtable[2])(self._ptr)
            self._ptr = c_void_p()


# ── registre ──────────────────────────────────────────────────────────────────
_KLUC_WALLPAPERS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers"
_HISTORIA = tuple(f"BackgroundHistoryPath{i}" for i in range(5))
# BackgroundType: 0 obrazok, 1 jednofarebne, 2 prezentacia, 3 Windows Spotlight.
_TYP_OBRAZOK = 0
_TYP_FARBA = 1
_NAZVY_TYPOV = {2: "prezentácia (slideshow)", 3: "Windows Spotlight"}


def _citaj_wallpapers() -> dict:
    vysledok: dict = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KLUC_WALLPAPERS) as k:
            for meno in ("BackgroundType", *_HISTORIA):
                try:
                    vysledok[meno] = winreg.QueryValueEx(k, meno)[0]
                except FileNotFoundError:
                    pass
    except OSError:
        pass
    return vysledok


def _zapis_historiu(historia: dict) -> None:
    """Vrati zoznam „Posledne obrazky" v Nastaveniach, aky bol pred prehravacom."""
    if not historia:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KLUC_WALLPAPERS, 0, winreg.KEY_SET_VALUE) as k:
            for meno in _HISTORIA:
                if meno in historia:
                    winreg.SetValueEx(k, meno, 0, winreg.REG_SZ, str(historia[meno]))
    except OSError:
        pass


def _spotlight_cesta(cesta: str) -> bool:
    nizke = cesta.lower()
    return any(s in nizke for s in ("irisservice", "contentdeliverymanager", "desktopspotlight"))


def _transcoded(monitor_index: int) -> Path | None:
    """Kopia aktualneho pozadia, ktoru si drzi sam Windows.

    Pouzije sa, ked povodny obrazok na disku uz nie je (clovek ho zmazal) —
    plocha ho ale stale ukazuje, lebo Windows si ho pri nastaveni skopiroval.
    """
    temy = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Themes"
    for meno in (f"Transcoded_{monitor_index:03d}", "TranscodedWallpaper"):
        kandidat = temy / meno
        if kandidat.is_file():
            return kandidat
    return None


def _rovnake(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


_SPI_SETDESKWALLPAPER = 0x0014
_SPIF_UPDATEINIFILE_SENDCHANGE = 0x01 | 0x02


def _jednofarebne() -> None:
    ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
        _SPI_SETDESKWALLPAPER, 0, ctypes.c_wchar_p(""), _SPIF_UPDATEINIFILE_SENDCHANGE
    )


# ── samotne pozadie ───────────────────────────────────────────────────────────
@dataclass
class Album:
    """Co ma byt na ploche. `kluc` rozlisuje albumy — rovnaky = netreba menit."""
    kluc: str
    obal: bytes
    interpret: str = ""
    album: str = ""
    rok: str = ""
    farby: dict[str, str] | None = None


@dataclass
class _Povodne:
    monitory: dict[str, str] = field(default_factory=dict)   # monitor -> cesta
    zalohy: dict[str, str] = field(default_factory=dict)     # monitor -> kopia obrazka
    pozicia: int = POZICIA_VYPLNIT
    typ: int = _TYP_OBRAZOK
    historia: dict = field(default_factory=dict)
    nase: dict[str, str] = field(default_factory=dict)       # monitor -> nas obrazok

    def do_json(self) -> dict:
        return {
            "monitory": self.monitory, "zalohy": self.zalohy, "pozicia": self.pozicia,
            "typ": self.typ, "historia": self.historia, "nase": self.nase,
        }

    @classmethod
    def z_json(cls, d: dict) -> "_Povodne":
        return cls(
            monitory=dict(d.get("monitory") or {}), zalohy=dict(d.get("zalohy") or {}),
            pozicia=int(d.get("pozicia", POZICIA_VYPLNIT)), typ=int(d.get("typ", 0)),
            historia=dict(d.get("historia") or {}), nase=dict(d.get("nase") or {}),
        )


class PozadiePlochy:
    """Meni pozadie plochy vo vlastnom vlakne. Vsetky metody sa vracaju hned.

    `stav` je kratky text pre okno nastaveni a /health — co sa naposledy
    stalo, alebo preco sa pozadie nemeni.
    """

    def __init__(self, priecinok: Path | None = None, *, okno=None) -> None:
        self.priecinok = priecinok or predvoleny_priecinok()
        self._fronta: "queue.Queue[tuple]" = queue.Queue()
        self._vlakno: threading.Thread | None = None
        self._povodne: _Povodne | None = None
        self._aktualny_kluc = ""
        self._strana = 0       # strieda a/b, aby Windows obrazok naozaj nacital znova
        self.stav = "čaká na hudbu"
        self.aktivne = False   # na ploche je prave obrazok od prehravaca

    @property
    def subor_stavu(self) -> Path:
        return self.priecinok / "povodne.json"

    # -- verejne, z hlavneho vlakna --------------------------------------------
    def spusti(self) -> None:
        if self._vlakno is not None:
            return
        self._vlakno = threading.Thread(target=self._beh, daemon=True, name="pozadie-plochy")
        self._vlakno.start()
        # Zvysok po predoslom behu, ktory skoncil padom alebo vypnutim PC.
        self._fronta.put(("obnov_po_pade",))

    def ukaz(self, album: Album) -> None:
        self._fronta.put(("ukaz", album))

    def vrat(self, *, pockaj: float = 0.0) -> None:
        """Vrati povodne pozadie. S `pockaj` blokuje (pri ukonceni appky)."""
        hotovo = threading.Event()
        self._fronta.put(("vrat", hotovo))
        if pockaj > 0:
            hotovo.wait(pockaj)

    def zastav(self, *, pockaj: float = 3.0) -> None:
        self.vrat(pockaj=pockaj)
        self._fronta.put(("koniec",))

    # -- vlakno ----------------------------------------------------------------
    def _beh(self) -> None:
        _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        while True:
            prikaz = self._fronta.get()
            # Viac "ukaz" za sebou (rychle preskakovanie skladieb) = plati posledne.
            while prikaz[0] == "ukaz":
                try:
                    dalsi = self._fronta.get_nowait()
                except queue.Empty:
                    break
                if dalsi[0] != "ukaz":
                    self._vykonaj(prikaz)
                    prikaz = dalsi
                    break
                prikaz = dalsi
            if prikaz[0] == "koniec":
                return
            self._vykonaj(prikaz)

    def _vykonaj(self, prikaz: tuple) -> None:
        try:
            if prikaz[0] == "ukaz":
                self._ukaz(prikaz[1])
            elif prikaz[0] == "vrat":
                try:
                    self._vrat()
                finally:
                    prikaz[1].set()
            elif prikaz[0] == "obnov_po_pade":
                self._obnov_po_pade()
        except Exception as exc:  # nic z toho nesmie zhodit vlakno
            self.stav = f"chyba: {exc}"

    # -- logika ----------------------------------------------------------------
    def _uloz_stav(self) -> None:
        if self._povodne is None:
            return
        self.priecinok.mkdir(parents=True, exist_ok=True)
        docasny = self.subor_stavu.with_suffix(".tmp")
        docasny.write_text(json.dumps(self._povodne.do_json(), ensure_ascii=False, indent=1),
                           encoding="utf-8")
        docasny.replace(self.subor_stavu)

    def _zmaz_stav(self) -> None:
        try:
            self.subor_stavu.unlink()
        except FileNotFoundError:
            pass

    def _zapamataj_povodne(self, dw: _DesktopWallpaper) -> str:
        """Odfoti pozadie pred prvou zmenou. Vrati dovod, preco menit nemozno, alebo ""."""
        registre = _citaj_wallpapers()
        typ = int(registre.get("BackgroundType", _TYP_OBRAZOK) or 0)
        if typ in _NAZVY_TYPOV:
            return f"pozadie nemením: máš zapnutú {_NAZVY_TYPOV[typ]}"
        if typ not in (_TYP_OBRAZOK, _TYP_FARBA):
            return f"pozadie nemením: neznámy typ pozadia ({typ})"
        if dw.stav() & _DSS_SLIDESHOW:
            return "pozadie nemením: máš zapnutú prezentáciu (slideshow)"

        povodne = _Povodne(typ=typ, historia={k: v for k, v in registre.items() if k in _HISTORIA})
        try:
            povodne.pozicia = dw.pozicia()
        except OSError:
            pass
        self.priecinok.mkdir(parents=True, exist_ok=True)
        for i, monitor in enumerate(dw.monitory()):
            cesta = dw.pozadie(monitor) if typ == _TYP_OBRAZOK else ""
            if cesta and _spotlight_cesta(cesta):
                return "pozadie nemením: máš zapnutý Windows Spotlight"
            if cesta and self._je_nas_subor(cesta):
                # Obrazok od prehravaca bez zaznamu o povodnom (zaznam sa
                # stratil). Za povodne sa berie posledny cudzi obrazok
                # z historie v Nastaveniach.
                cesta = next(
                    (str(h) for k, h in sorted(povodne.historia.items())
                     if h and not self._je_nas_subor(str(h)) and Path(str(h)).is_file()),
                    "",
                )
            povodne.monitory[monitor] = cesta
            zdroj = Path(cesta) if cesta and Path(cesta).is_file() else _transcoded(i)
            if zdroj is not None and zdroj.is_file():
                kopia = self.priecinok / f"povodne-{i}{zdroj.suffix.lower() or '.jpg'}"
                try:
                    shutil.copy2(zdroj, kopia)
                    povodne.zalohy[monitor] = str(kopia)
                except OSError:
                    pass
        self._povodne = povodne
        self._uloz_stav()
        return ""

    def _je_nas_subor(self, cesta: str) -> bool:
        """Obrazok albumu od prehravaca (nie povodne pozadie ulozene u nas)."""
        try:
            subor = Path(cesta).resolve()
            return subor.parent == self.priecinok.resolve() and subor.name.startswith("album-")
        except OSError:
            return False

    def _je_nase_na_ploche(self, dw: _DesktopWallpaper) -> bool:
        if self._povodne is None or not self._povodne.nase:
            return False
        try:
            for monitor in dw.monitory():
                nase = self._povodne.nase.get(monitor)
                if nase and _rovnake(dw.pozadie(monitor), nase):
                    return True
        except OSError:
            return False
        return False

    def _ukaz(self, album: Album) -> None:
        if album.kluc == self._aktualny_kluc and self.aktivne:
            return
        dw = _DesktopWallpaper()
        try:
            if self._povodne is None or not self.aktivne or not self._je_nase_na_ploche(dw):
                # Kym na ploche nie je obrazok od prehravaca, povodne je to,
                # co tam prave je — aj ked si ho clovek medzicasom zmenil sam.
                # Jeho volba je odteraz to, k comu sa bude vracat.
                self._povodne = None
                self.aktivne = False
                dovod = self._zapamataj_povodne(dw)
                if dovod:
                    self.stav = dovod
                    self._zmaz_stav()
                    return

            self._strana ^= 1
            nase: dict[str, str] = {}
            for i, (monitor, sirka, vyska) in enumerate(dw.zapojene()):
                obrazok = zloz_obrazok(album.obal, sirka, vyska, interpret=album.interpret,
                                       album=album.album, rok=album.rok, farby=album.farby)
                if obrazok is None:
                    self.stav = "obal sa nedá načítať"
                    return
                cesta = self.priecinok / f"album-{i}-{'ab'[self._strana]}.jpg"
                if not obrazok.save(str(cesta), "JPG", 92):
                    self.stav = f"obrázok sa nedá uložiť do {cesta}"
                    return
                nase[monitor] = str(cesta)
            # Najprv zapisat, co je nase — keby appka spadla hned po zmene,
            # dalsie spustenie musi vediet, ze na ploche je obrazok od nej.
            self._povodne.nase = nase
            self._uloz_stav()
            dw.nastav_poziciu(POZICIA_VYPLNIT)
            for monitor, cesta in nase.items():
                dw.nastav(monitor, cesta)
            self._aktualny_kluc = album.kluc
            self.aktivne = True
            popis = " – ".join(x for x in (album.interpret, album.album) if x)
            self.stav = f"na ploche: {popis}" if popis else "na ploche je obal albumu"
        finally:
            dw.uvolni()

    def _vrat(self) -> None:
        if self._povodne is None:
            self.aktivne = False
            self._aktualny_kluc = ""
            return
        povodne = self._povodne
        if povodne.nase:
            dw = _DesktopWallpaper()
            try:
                if self._je_nase_na_ploche(dw):
                    self._obnov(dw, povodne)
                    self.stav = "vrátené pôvodné pozadie"
                else:
                    self.stav = "pozadie si medzitým zmenil — nechávam ho"
            finally:
                dw.uvolni()
        self._povodne = None
        self._zmaz_stav()
        self.aktivne = False
        self._aktualny_kluc = ""
        # Kopie povodneho a obrazky albumov uz netreba: Windows si pozadie drzi
        # vo vlastnej kopii (TranscodedWallpaper).
        for vzor in ("povodne-*", "album-*"):
            for subor in self.priecinok.glob(vzor):
                try:
                    subor.unlink()
                except OSError:
                    pass

    def _obnov(self, dw: _DesktopWallpaper, povodne: _Povodne) -> None:
        if povodne.typ == _TYP_FARBA:
            _jednofarebne()
        else:
            try:
                dw.nastav_poziciu(povodne.pozicia)
            except OSError:
                pass
            zname = povodne.monitory
            nahradny = next((c for c in zname.values() if c and Path(c).is_file()), "")
            for monitor, _sirka, _vyska in dw.zapojene():
                cesta = zname.get(monitor, nahradny)
                if cesta and not Path(cesta).is_file():
                    cesta = povodne.zalohy.get(monitor, "")
                if not cesta:
                    cesta = next((z for z in povodne.zalohy.values() if Path(z).is_file()), "")
                if cesta and Path(cesta).name.startswith("povodne-"):
                    # Povodny subor zmizol a vracia sa kopia. Tie sa po navrate
                    # mazu, takze pozadie dostane vlastnu, ktora ostane.
                    trvala = self.priecinok / Path(cesta).name.replace("povodne-", "obnovene-", 1)
                    try:
                        shutil.copy2(cesta, trvala)
                        cesta = str(trvala)
                    except OSError:
                        pass
                if cesta:
                    dw.nastav(monitor, cesta)
        _zapis_historiu(povodne.historia)

    def _obnov_po_pade(self) -> None:
        if not self.subor_stavu.exists():
            return
        try:
            self._povodne = _Povodne.z_json(json.loads(self.subor_stavu.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            self._zmaz_stav()
            return
        self.aktivne = True
        self._vrat()
        if self.stav == "vrátené pôvodné pozadie":
            self.stav = "vrátené pôvodné pozadie (po minulom behu)"


def kluc_albumu(interpret: str, album: str, obal: bytes) -> str:
    """Ten isty album = to iste pozadie, aj ked sa skladba zmeni."""
    h = hashlib.sha1(obal).hexdigest()[:12]
    return f"{interpret.strip().lower()}|{album.strip().lower()}|{h}"
