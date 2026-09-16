r"""Dohladanie nazvu albumu na Metal Archives.

`nazvy.py` rozhoduje offline a opatrne: ked z nazvu priecinka nevie, kde konci
meno kapely a zacina album, nechá ho tak. Pri metale to ale nie je nutne —
kapela aj album su takmer vzdy na Metal Archives, takze sa staci opytat.

    Blind-Guardian-Somewhere-2026-GRP
      -> skusi kapelu "Blind Guardian Somewhere"   (MA: nic)
      -> skusi kapelu "Blind Guardian"             (MA: diskografia)
      -> v diskografii najde album, ktoreho slova su v nazve priecinka
      -> Blind Guardian - Somewhere - 2026

Ked MA nic nenajde (alebo neodpovie), vrati sa `None` a priecinok sa rozbali
pod povodnym nazvom. Tipovat sa nema: cudzia kapela v nazve priecinka je horsia
nez povodny neporiadok.

Hlada sa VYHRADNE podla mena kapely a zhoda albumu sa robi az offline
(`nazvy.najdi_v_zozname`). Dovod: v nazve priecinka byva za albumom este meno
vydavajucej skupiny (`-GRP`, `by necroscum`) a to by hladanie albumu na MA
zabilo — takto neprekaza, lebo sa pyta opacne: su slova albumu z MA obsiahnute
v nazve priecinka?
"""

from __future__ import annotations

import re
import threading
from html import unescape

from music_player import config_loader, nazvy

#: Kolko mien kapely sa nanajvys skusi. Kazde je jedno hladanie na MA
#: (a `metal_archives` medzi dopytmi caka 1,5 s), takze strop drzi rozbalovanie
#: v case, ktory sa da vydrzat pri jednom archive.
MAX_KANDIDATOV = 4

_ODKAZ = re.compile(r'href="[^"]*/(\d+)"[^>]*>([^<]+)<')

_cache_lock = threading.Lock()
_cache: dict[str, list[tuple[str, str]]] = {}


def zapnute() -> bool:
    hodnota = config_loader.load_config().get("NAZVY_MA", "ano").strip().lower()
    return hodnota not in {"nie", "no", "0", "false", "vypnute"}


def _meno_z_odkazu(html: str) -> str:
    m = _ODKAZ.search(html or "")
    return unescape(m.group(2)).strip() if m else ""


def diskografia(kapela: str) -> list[tuple[str, str]]:
    """[(kapela, album)] podla MA. Nedostupne MA vrati prazdny zoznam.

    Mena sa beru z odpovede, nie zo vstupu — MA pozna spravny zapis vratane
    diakritiky a interpunkcie (`I, Scvlptor`, `Boötes Void`).
    """
    from music_player import metal_archives

    kluc = kapela.strip().casefold()
    if not kluc:
        return []
    with _cache_lock:
        if kluc in _cache:
            return _cache[kluc]

    odpoved = metal_archives._get(
        f"{metal_archives.BASE_URL}/search/ajax-advanced/searching/albums/",
        params={
            "bandName": metal_archives._normalize_text(kapela),
            "releaseTitle": "",
            "sEcho": "1",
            "iDisplayStart": "0",
            "iDisplayLength": "200",
        },
    )
    dvojice: list[tuple[str, str]] = []
    if odpoved is not None:
        try:
            riadky = odpoved.json().get("aaData", [])
        except Exception:  # noqa: BLE001 - MA vie vratit aj HTML chybu
            riadky = []
        for riadok in riadky:
            if len(riadok) < 2:
                continue
            meno = _meno_z_odkazu(riadok[0])
            album = _meno_z_odkazu(riadok[1])
            if meno and album:
                dvojice.append((meno, album))

    with _cache_lock:
        _cache[kluc] = dvojice
    return dvojice


def dohladaj(surovy: str) -> nazvy.Nazov | None:
    """`Interpret - Album - Rok` podla MA, alebo `None`, ked sa nic nenaslo."""
    if not zapnute():
        return None
    v_nazve, _rok = nazvy.rozlozenie(surovy)
    if len(v_nazve) < 2:
        return None

    # Od najdlhsieho mena kapely: "Blind Guardian" musi vyhrat nad "Blind".
    najviac = min(len(v_nazve) - 1, MAX_KANDIDATOV)
    for pocet in range(najviac, 0, -1):
        najdene = nazvy.najdi_v_zozname(surovy, diskografia(" ".join(v_nazve[:pocet])))
        if najdene is not None:
            return najdene
    return None
