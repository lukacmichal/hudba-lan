"""Persistent file-based cache for album art, lyrics, and metadata.

Cache files are stored alongside the music files:
  - folder.jpg          — album cover art
  - .lyrics/{title}.txt — lyrics per track (sentinel __NO_LYRICS__ = searched,
                          not found; expires, see treba_znova_hladat)
  - album_meta.json     — extended album metadata (label, date, genre, lineup)
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

_NO_LYRICS_SENTINEL = "__NO_LYRICS__"


def _album_dir(track_path: str) -> Path:
    return Path(track_path).parent


def _sanitize_filename(name: str) -> str:
    """Remove characters illegal in Windows filenames."""
    return re.sub(r'[<>:"/\\|?*]', "_", name.strip())


# ── cover art ─────────────────────────────────────────────────────────────────


def read_cached_cover(track_path: str) -> bytes | None:
    """Read folder.jpg from the album directory. Returns None if missing."""
    path = _album_dir(track_path) / "folder.jpg"
    try:
        if path.is_file() and path.stat().st_size > 100:
            return path.read_bytes()
    except OSError:
        pass
    return None


def write_cached_cover(track_path: str, data: bytes) -> None:
    """Write cover art as folder.jpg in the album directory."""
    path = _album_dir(track_path) / "folder.jpg"
    try:
        path.write_bytes(data)
    except OSError:
        pass


# ── lyrics ────────────────────────────────────────────────────────────────────


def _lyrics_path(track_path: str, title: str) -> Path:
    safe = _sanitize_filename(title) or "unknown"
    return _album_dir(track_path) / ".lyrics" / f"{safe}.txt"


# „Nenašlo sa“ nie je trvalá pravda: Metal Archives dopĺňa texty až dni po
# vydaní albumu (Nunslaughter, 9/2026 — prehrávač ukazoval „nenašli sa“, hoci
# texty už na MA boli). Značka preto platí len obmedzene. Kým je od prvého
# hľadania menej než _NOVE_DNI, skúša sa znova po dni; potom už text zjavne
# neexistuje (inštrumentálka, obskúrny split) a stačí raz za mesiac.
_NOVE_DNI = 60
_ZNOVA_NOVE_S = 1 * 86400
_ZNOVA_STARE_S = 30 * 86400


def treba_znova_hladat(prve: float, posledne: float, teraz: float) -> bool:
    """Je značka „nenašlo sa“ už taká stará, že sa oplatí spýtať znova?

    prve     — kedy sa skladba hľadala prvýkrát (vznik súboru so značkou)
    posledne — kedy naposledy (posledný zápis značky)
    """
    interval = _ZNOVA_NOVE_S if teraz - prve < _NOVE_DNI * 86400 else _ZNOVA_STARE_S
    return teraz - posledne >= interval


def _casy_znacky(path: Path) -> tuple[float, float]:
    """(prvé, posledné) hľadanie zo súboru so značkou.

    Obsah súboru ostáva presne `__NO_LYRICS__` — staršia verzia prehrávača na
    druhom notebooku by inak časy zobrazila ako text piesne. Prvé hľadanie je
    preto čas vzniku súboru (prepísanie ho na Windows nemení), posledné je
    čas zápisu.
    """
    st = path.stat()
    vznik = getattr(st, "st_birthtime", st.st_ctime)
    return min(vznik, st.st_mtime), st.st_mtime


def read_cached_lyrics(track_path: str, title: str, teraz: float | None = None) -> str | None:
    """Read cached lyrics.

    Returns:
        None  — never searched, or "not found" is old enough to search again
        ""    — fresh sentinel (searched recently, not found)
        str   — lyrics text
    """
    path = _lyrics_path(track_path, title)
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8").strip()
        if text == _NO_LYRICS_SENTINEL:
            prve, posledne = _casy_znacky(path)
            if treba_znova_hladat(prve, posledne, time.time() if teraz is None else teraz):
                return None
            return ""
        return text
    except OSError:
        return None


def ma_znacku_nenaslo(track_path: str, title: str) -> bool:
    """Leží na disku značka „hľadané, nenašlo sa“ (čerstvá či stará)?"""
    path = _lyrics_path(track_path, title)
    try:
        return path.is_file() and path.read_text(encoding="utf-8").strip() == _NO_LYRICS_SENTINEL
    except OSError:
        return False


def zabudni_nenaslo_albumu(track_path: str) -> int:
    """Zmaž značky „nenašlo sa“ pri všetkých skladbách albumu. Vráti počet.

    Tlačidlo „Načítať texty“: keď MA doplnil texty jednej skladbe, doplnil ich
    obvykle celému albumu — ostatné skladby sa tak spýtajú hneď pri prehratí,
    nie až o deň. Nájdené texty ani preklady sa nemažú.
    """
    zmazane = 0
    priecinok = _album_dir(track_path) / ".lyrics"
    try:
        subory = list(priecinok.glob("*.txt"))
    except OSError:
        return 0
    for subor in subory:
        if subor.name.endswith(".sk.txt"):
            continue
        try:
            if subor.read_text(encoding="utf-8").strip() == _NO_LYRICS_SENTINEL:
                subor.unlink()
                zmazane += 1
        except OSError:
            pass
    return zmazane


def zmaz_preklad(track_path: str, title: str) -> None:
    """Preklad k textu, ktorý sa medzitým zmenil, už neplatí."""
    try:
        _translation_path(track_path, title).unlink(missing_ok=True)
    except OSError:
        pass


def write_cached_lyrics(track_path: str, title: str, text: str) -> None:
    """Write lyrics to disk. Writes sentinel if text is empty."""
    path = _lyrics_path(track_path, title)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = text.strip() if text.strip() else _NO_LYRICS_SENTINEL
        path.write_text(content, encoding="utf-8")
    except OSError:
        pass


# ── slovenský preklad textu ───────────────────────────────────────────────────


def _translation_path(track_path: str, title: str) -> Path:
    safe = _sanitize_filename(title) or "unknown"
    return _album_dir(track_path) / ".lyrics" / f"{safe}.sk.txt"


def read_cached_translation(track_path: str, title: str) -> str | None:
    """Slovak translation of the lyrics, or None when there is none yet.

    Zámerne tu NIE JE sentinel „hľadané, nenašlo sa“ ako pri textoch: text sa
    buď na webe nájde, alebo nie, ale preklad zlyhá vždy len dočasne — sieť,
    kvóta, výpadok DeepL. Zapísať neúspech by znamenalo, že sa o skladbu už
    nikdy nepokúsime.
    """
    path = _translation_path(track_path, title)
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_cached_translation(track_path: str, title: str, text: str) -> None:
    """Ulož preklad vedľa textu. Prázdny preklad sa nezapisuje.

    Vďaka tomuto sa každá skladba prekladá z kvóty DeepL práve raz, aj keď ju
    prehráš stokrát.
    """
    if not text.strip():
        return
    path = _translation_path(track_path, title)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.strip(), encoding="utf-8")
    except OSError:
        pass


# ── album metadata ────────────────────────────────────────────────────────────


def read_cached_album_meta(track_path: str) -> dict | None:
    """Read album_meta.json. Returns parsed dict or None."""
    path = _album_dir(track_path) / "album_meta.json"
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def write_cached_album_meta(track_path: str, meta: dict) -> None:
    """Write album metadata as JSON."""
    path = _album_dir(track_path) / "album_meta.json"
    try:
        path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
