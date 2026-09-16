"""Zoznamy skladieb pre tlacidla "Spanok" a "Spanok 2".

Obe tlacidla robia to iste, len z ineho suboru: vezmu svoj zoznam, pridaju ho
na koniec playlistu a zacnu ho hrat. Preto su tu spolu a nie kazde zvlast —
rozdiel je jedine v tom, ktory M3U subor a ktore kluce v `config.txt` sa citaju.

Kazdy zoznam je obycajny M3U vedla `config.txt`, takze sa da menit aj rucne
v poznamkovom bloku, aj cez dialog v aplikacii. Kolko skladieb sa pusti, urcuje
pocet riadkov v subore — ziadne dalsie nastavenie poctu neexistuje.

CO SA DEJE PO UKONCENI PREHRAVACA
---------------------------------
Skladby, ktore tlacidlo do playlistu pridalo, sa pri ukonceni appky zase
odstrania — playlist teda ostane taky, aky bol predtym. Da sa to vypnut
v `config.txt`:

    SPANOK_NECHAT_V_PLAYLISTE=ano
    SPANOK2_NECHAT_V_PLAYLISTE=ano

`ano` = skladby v playliste ostanu aj na dalsi den. Ked kluc chyba, plati `nie`.

Do 1. 9. 2026 sa playlist vracal uz po dohrati poslednej skladby a riadila to
znacka `#SPANOK2-VRATIT-PLAYLIST` v samotnom M3U. To malo dva problemy:
navrat prisiel v momente, ked sa PC prave uspaval (takze sa casto ani nestihol
ulozit), a nastavenie bolo schovane v subore so skladbami namiesto v konfiguraku
k ostatnym volbam. Stara znacka je dnes obycajny komentar a ignoruje sa.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from music_player.config_loader import load_config, set_value
from music_player.models import is_audio_file

_APP_DIR = Path(__file__).resolve().parent.parent

SPANOK = "spanok"
SPANOK2 = "spanok2"

# Pre kazde tlacidlo: kluc s cestou, default meno suboru, kluc "nechat v
# playliste" a nazov, ktory sa ukazuje cloveku.
_ZOZNAMY = {
    SPANOK: ("SPANOK_PLAYLIST", "spanok.m3u", "SPANOK_NECHAT_V_PLAYLISTE", "Spánok"),
    SPANOK2: ("SPANOK2_PLAYLIST", "spanok2.m3u", "SPANOK2_NECHAT_V_PLAYLISTE", "Spánok 2"),
}

_TRUE_WORDS = {"ano", "áno", "1", "true", "yes", "on"}
_FALSE_WORDS = {"nie", "0", "false", "no", "off"}


@dataclass(slots=True)
class Zoznam:
    """Obsah jedneho M3U: co sa ma hrat a ktore riadky sa nenasli."""

    tracks: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def nazov(ktory: str) -> str:
    """Nazov tlacidla, ako sa ukazuje cloveku ("Spánok" / "Spánok 2")."""
    return _ZOZNAMY[ktory][3]


def kluc_nechat(ktory: str) -> str:
    """Meno kluca v config.txt, ktorym sa riadi ponechanie skladieb v playliste."""
    return _ZOZNAMY[ktory][2]


def playlist_path(ktory: str) -> Path:
    """Cesta k M3U suboru daneho tlacidla."""
    kluc, default_meno, _, _ = _ZOZNAMY[ktory]
    raw = load_config().get(kluc, "").strip()
    if not raw:
        return _APP_DIR / default_meno
    candidate = Path(os.path.expandvars(raw)).expanduser()
    if not candidate.is_absolute():
        candidate = _APP_DIR / candidate
    return candidate


def nechat_v_playliste(ktory: str) -> bool:
    """Maju skladby ostat v playliste aj po ukonceni prehravaca?"""
    kluc = _ZOZNAMY[ktory][2]
    hodnota = load_config().get(kluc, "").strip().strip('"').lower()
    if hodnota in _TRUE_WORDS:
        return True
    if hodnota in _FALSE_WORDS:
        return False
    return False


def nastav_nechat(ktory: str, hodnota: bool) -> None:
    """Zapise volbu "nechat v playliste" do config.txt."""
    set_value(_ZOZNAMY[ktory][2], "ano" if hodnota else "nie")


def load(ktory: str) -> Zoznam:
    """Nacita zoznam zo suboru.

    Chybajuce riadky sa nezahadzuju ticho — appka ich ukaze pouzivatelovi, aby
    vedel, ktore cesty su rozbite (presunuty/premenovany subor).
    """
    path = playlist_path(ktory)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Zoznam()

    result = Zoznam()
    base_dir = path.parent
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry = Path(os.path.expandvars(line)).expanduser()
        if not entry.is_absolute() and not line.startswith(("\\", "/")):
            entry = base_dir / entry
        try:
            entry = entry.resolve()
        except OSError:
            result.missing.append(line)
            continue
        if entry.is_file() and is_audio_file(str(entry)):
            result.tracks.append(str(entry))
        else:
            result.missing.append(line)
    return result


def save(ktory: str, tracks: list[str]) -> Path:
    """Prepise zoznam. Vracia cestu k zapisanemu suboru."""
    path = playlist_path(ktory)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_header(ktory)]
    lines.extend(str(track) for track in tracks)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def append(ktory: str, paths: list[str]) -> tuple[int, Path]:
    """Prida cesty na koniec zoznamu, duplicity preskoci.

    Vracia (kolko skladieb naozaj pribudlo, cesta k suboru).
    """
    current = load(ktory)
    known = {p.lower() for p in current.tracks} | {m.lower() for m in current.missing}
    added: list[str] = []
    for raw in paths:
        resolved = str(Path(raw).expanduser().resolve())
        if resolved.lower() in known:
            continue
        known.add(resolved.lower())
        added.append(resolved)
    if not added:
        return 0, playlist_path(ktory)
    return len(added), save(ktory, current.tracks + current.missing + added)


def _header(ktory: str) -> str:
    meno = nazov(ktory)
    kluc_nechat = _ZOZNAMY[ktory][2]
    return (
        "#EXTM3U\n"
        f'# Zoznam skladieb pre tlacidlo "{meno}" v Metal Music Playeri.\n'
        "# Jedna cesta k suboru na riadok, poradie riadkov = poradie prehravania.\n"
        "# Riadky zacinajuce # su komentare a ignoruju sa.\n"
        "# Subor sa da editovat rucne, alebo v appke: prave tlacidlo mysi\n"
        f'# na tlacidle "{meno}", pripadne prave tlacidlo na skladbe v playliste\n'
        f'# a "Pridat do {meno}".\n'
        "#\n"
        "# Ci skladby po ukonceni prehravaca ostanu v playliste, sa uz neriesi\n"
        f"# tu, ale v config.txt klucom {kluc_nechat}=ano / nie.\n"
    )
