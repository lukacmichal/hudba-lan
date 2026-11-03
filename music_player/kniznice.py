"""Doinstalovanie volitelnych kniznic, ked v Pythone chybaju.

Aktualizacia z NAS-u kopiruje len subory appky — Python kniznice
nedoinstaluje (a `aktualizuj.ps1` sa pri update berie zo STAREJ verzie,
takze by to nevedel ani po uprave). Kniznicu, ktoru nova verzia potrebuje,
si preto appka doinstaluje sama: na pozadi, cez `python -m pip`, bez okna.

Plati to pre volitelne veci — appka bez nich bezi dalej, len bez danej
funkcie. Dnes je to jedina: `winrt` na ovladanie medii vo Windows
(`windows_media.py`).

Nedostupny internet = ticho, skusi sa pri dalsom spusteni. Priebeh je
v `%TEMP%\\metalplayer-kniznice.log`.
"""
from __future__ import annotations

import importlib
import site
import subprocess
import sys
import tempfile
from datetime import datetime
from importlib import metadata
from pathlib import Path

LOG = Path(tempfile.gettempdir()) / "metalplayer-kniznice.log"

# Ovladanie medii vo Windows (System Media Transport Controls).
WINRT = (
    "winrt-runtime",
    "winrt-Windows.Foundation",
    "winrt-Windows.Foundation.Collections",
    "winrt-Windows.Media",
    "winrt-Windows.Media.Playback",
    "winrt-Windows.Storage",
    "winrt-Windows.Storage.Streams",
)
# Vyskusana verzia. Ma koliesko pre Python 3.9 az 3.14; novsi Python dostane
# najnovsiu (druhy pokus bez cisla verzie).
WINRT_VERZIA = "3.2.1"


def chybaju(baliky: tuple[str, ...] = WINRT) -> list[str]:
    """Ktore z balikov nie su nainstalovane. Nic neimportuje."""
    vysledok = []
    for balik in baliky:
        try:
            metadata.version(balik)
        except metadata.PackageNotFoundError:
            vysledok.append(balik)
    return vysledok


def python_s_konzolou() -> str:
    """python.exe vedla pythonw.exe — pip pod pythonw nema kam pisat."""
    spustitelny = Path(sys.executable)
    if spustitelny.name.lower() == "pythonw.exe":
        vedla = spustitelny.with_name("python.exe")
        if vedla.exists():
            return str(vedla)
    return str(spustitelny)


def _zapis(text: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")
    except OSError:
        pass


def nainstaluj(baliky: tuple[str, ...] = WINRT, verzia: str = WINRT_VERZIA,
               *, timeout: float = 600) -> tuple[bool, str]:
    """Doinstaluje baliky cez pip. Blokuje — volat z vlakna.

    Vracia (podarilo sa, kratky popis chyby). Ked site-packages nie je
    zapisovatelny, pip sam prejde na --user; ten priecinok sa potom prida
    do sys.path, aby sa kniznica dala importovat bez restartu appky.
    """
    python = python_s_konzolou()
    pokusy = [[f"{b}=={verzia}" for b in baliky]] if verzia else []
    pokusy.append(list(baliky))
    chyba = ""
    for specifikacia in pokusy:
        prikaz = [python, "-m", "pip", "install", "--disable-pip-version-check",
                  "--no-input", *specifikacia]
        _zapis("spustam: " + " ".join(prikaz))
        try:
            vysledok = subprocess.run(
                prikaz, capture_output=True, text=True, timeout=timeout,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            chyba = f"pip sa nedal spustiť: {exc}"
            _zapis(chyba)
            continue
        _zapis(f"pip skoncil s kodom {vysledok.returncode}")
        for riadok in (vysledok.stdout + vysledok.stderr).splitlines()[-25:]:
            _zapis("  " + riadok)
        if vysledok.returncode == 0:
            break
        posledny = next((r for r in reversed(vysledok.stderr.splitlines()) if r.strip()), "")
        chyba = posledny.strip() or f"pip skončil s kódom {vysledok.returncode}"

    importlib.invalidate_caches()
    if chybaju(baliky):
        return False, chyba or "knižnica sa nenainštalovala"
    _pridaj_user_site()
    _zapis("hotovo")
    return True, ""


def _pridaj_user_site() -> None:
    try:
        cesta = site.getusersitepackages()
    except Exception:
        return
    if cesta and Path(cesta).is_dir() and cesta not in sys.path:
        site.addsitedir(cesta)
        importlib.invalidate_caches()
