"""Rozsirenie pre Firefox na tomto pocitaci: co je nainstalovane a co na NAS-e.

Firefox rozsirenie nainstalovane zo suboru sa samo neaktualizuje. Novu verziu
treba vo Firefoxe raz potvrdit („Pridat") na kazdom notebooku — a prave na
druhom notebooku sa na to lahko zabudne. Prehravac preto porovna, co ma
Firefox nainstalovane (`extensions.json` v jeho profile, len citanie), s tym,
co lezi na NAS-e, a vie Firefox otvorit rovno s chybajucimi balikmi.
Potvrdenie „Pridat" vo Firefoxe ostava na cloveku.
"""
from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import tempfile
import winreg
import zipfile
from dataclasses import dataclass
from pathlib import Path

NAS_PRIECINOK = Path(r"\\nas.local\Android\PlayerPC\firefox")
HLAVNE_ID = "metal-music-player@lukacmichal"


@dataclass(frozen=True)
class Balik:
    subor: Path
    id: str
    verzia: str
    nazov: str


def _verzia(text: str) -> tuple[int, ...]:
    casti = []
    for kus in str(text).split("."):
        cislo = "".join(ch for ch in kus if ch.isdigit())
        casti.append(int(cislo) if cislo else 0)
    return tuple(casti)


def novsia(a: str, b: str) -> bool:
    return _verzia(a) > _verzia(b)


# ── Firefox na tomto pocitaci ────────────────────────────────────────────────
def firefox_exe() -> str:
    for koren in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(koren, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe") as k:
                cesta = winreg.QueryValueEx(k, "")[0]
                if cesta and Path(cesta).is_file():
                    return cesta
        except OSError:
            pass
    for kandidat in (r"C:\Program Files\Mozilla Firefox\firefox.exe",
                     r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"):
        if Path(kandidat).is_file():
            return kandidat
    return ""


def predvoleny_profil() -> Path | None:
    """Profil, ktory Firefox otvara (sekcia [Install...] v profiles.ini)."""
    koren = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    ini = configparser.ConfigParser()
    try:
        ini.read(koren / "profiles.ini", encoding="utf-8")
    except (OSError, configparser.Error):
        return None

    def cesta(sekcia) -> Path | None:
        hodnota = sekcia.get("Default") if sekcia.name.startswith("Install") else sekcia.get("Path")
        if not hodnota:
            return None
        relativna = sekcia.get("IsRelative", "1") == "1" or sekcia.name.startswith("Install")
        return (koren / hodnota) if relativna else Path(hodnota)

    for sekcia in ini.values():
        if sekcia.name.startswith("Install"):
            p = cesta(sekcia)
            if p and p.is_dir():
                return p
    for sekcia in ini.values():
        if sekcia.name.startswith("Profile") and sekcia.get("Default") == "1":
            p = cesta(sekcia)
            if p and p.is_dir():
                return p
    return None


def nainstalovane(profil: Path | None = None) -> dict[str, str] | None:
    """id -> verzia nasich rozsireni vo Firefoxe. None = Firefox/profil nie je."""
    profil = profil or predvoleny_profil()
    if profil is None:
        return None
    try:
        data = json.loads((profil / "extensions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    vysledok = {}
    for addon in data.get("addons", []):
        ident = str(addon.get("id", ""))
        if ident.endswith("@lukacmichal") and addon.get("location") == "app-profile":
            vysledok[ident] = str(addon.get("version", ""))
    return vysledok


# ── NAS ──────────────────────────────────────────────────────────────────────
def _precitaj_balik(xpi: Path) -> Balik | None:
    try:
        with zipfile.ZipFile(xpi) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8-sig"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
    gecko = (manifest.get("browser_specific_settings") or {}).get("gecko") or {}
    ident = str(gecko.get("id", ""))
    if not ident:
        return None
    return Balik(subor=xpi, id=ident, verzia=str(manifest.get("version", "")),
                 nazov=str(manifest.get("name", xpi.stem)))


def na_nas(priecinok: Path = NAS_PRIECINOK) -> list[Balik]:
    """Najnovsia verzia kazdeho rozsirenia na NAS-e. Nedostupny NAS = []."""
    from music_player.self_update import prihlas_na_share

    try:
        if not priecinok.is_dir():
            prihlas_na_share(priecinok)
        subory = sorted(priecinok.glob("*.xpi"))
    except OSError:
        return []
    najnovsie: dict[str, Balik] = {}
    for xpi in subory:
        balik = _precitaj_balik(xpi)
        if balik is None:
            continue
        stary = najnovsie.get(balik.id)
        if stary is None or novsia(balik.verzia, stary.verzia):
            najnovsie[balik.id] = balik
    return sorted(najnovsie.values(), key=lambda b: (b.id != HLAVNE_ID, b.nazov))


def treba_nainstalovat(na_nase: list[Balik], v_firefoxe: dict[str, str]) -> list[Balik]:
    """Co vo Firefoxe chyba alebo je starsie nez na NAS-e."""
    return [b for b in na_nase
            if b.id not in v_firefoxe or novsia(b.verzia, v_firefoxe[b.id])]


def otvor_vo_firefoxe(baliky: list[Balik]) -> str:
    """Otvori Firefox s balikmi — kazdy si vypyta „Pridat". Vrati chybu alebo ""."""
    exe = firefox_exe()
    if not exe:
        return "Firefox som na tomto počítači nenašiel."
    # Lokalna kopia: Firefox subory zo zdielaneho priecinka cez prikazovy
    # riadok nemusi otvorit, z disku vzdy.
    docasny = Path(tempfile.gettempdir()) / "metalplayer-firefox"
    docasny.mkdir(exist_ok=True)
    cesty = []
    for balik in baliky:
        ciel = docasny / balik.subor.name
        try:
            shutil.copy2(balik.subor, ciel)
        except OSError as exc:
            return f"{balik.subor.name} sa nedá skopírovať: {exc}"
        cesty.append(str(ciel))
    try:
        subprocess.Popen([exe, *cesty], close_fds=True)
    except OSError as exc:
        return f"Firefox sa nedá spustiť: {exc}"
    return ""
