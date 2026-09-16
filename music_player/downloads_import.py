r"""Hromadne rozbalenie hudobnych archivov z Downloads do C:\data\mp3\<rok>.

Rozbaluje sa cez `bsdtar` (C:\Windows\System32\tar.exe), ktory je sucastou
Windows a vie citat rar, zip aj 7z — netreba teda WinRAR ani 7-Zip.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from music_player import nazvy
from music_player.models import AUDIO_EXTENSIONS

ARCHIVE_EXTENSIONS = {".rar", ".zip", ".7z"}
#: Pouzije sa, ked `MP3_TARGET` v config.txt nie je vyplneny.
DEFAULT_TARGET_ROOT = Path(r"C:\data\mp3")
#: Rocne priecinky sa volaju `_2026`, `_2027`, ... — teda s podtrzitkom.
YEAR_PREFIX = "_"

_TAR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _long(path: Path | str) -> str:
    r"""Cesta s prefixom \?\, aby operacie nepadali na limite 260 znakov."""
    text = os.path.abspath(str(path))
    if text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):  # sietova cesta \\server\share
        return "\\\\?\\UNC" + text[1:]
    return "\\\\?\\" + text


def _rmtree(path: Path) -> None:
    shutil.rmtree(_long(path), ignore_errors=True)


def downloads_dir() -> Path:
    """Priecinok Downloads aktualneho pouzivatela."""
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"


def target_root() -> Path:
    """Korenovy priecinok z config.txt (`MP3_TARGET`), inak zabudovany default."""
    from music_player.config_loader import get_mp3_target

    configured = get_mp3_target()
    return Path(os.path.expandvars(configured)).expanduser() if configured else DEFAULT_TARGET_ROOT


def year_folder(year: int | None = None) -> str:
    """Nazov rocneho priecinka — pouzivatelova schema je `_2026`, `_2027`, ..."""
    return f"{YEAR_PREFIX}{year or datetime.now().year}"


def target_dir(root: Path | str | None = None, year: int | None = None) -> Path:
    r"""Cielovy priecinok pre aktualny rok, napr. C:\data\mp3\_2026."""
    return Path(root if root is not None else target_root()) / year_folder(year)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "cp1250"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def list_archive(archive: Path) -> list[str]:
    """Nazvy poloziek v archive; prazdny zoznam ak sa archiv necita."""
    try:
        proc = subprocess.run(
            [str(_TAR), "-tf", str(archive)],
            capture_output=True,
            creationflags=_NO_WINDOW,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in _decode(proc.stdout).splitlines() if line.strip()]


def has_audio(names: list[str]) -> bool:
    return any(Path(name).suffix.lower() in AUDIO_EXTENSIONS for name in names)


def find_music_archives(source: Path | str | None = None) -> list[Path]:
    """Archivy v Downloads, ktore obsahuju aspon jeden audio subor."""
    folder = Path(source) if source is not None else downloads_dir()
    if not folder.is_dir():
        return []
    candidates = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in ARCHIVE_EXTENSIONS
    )
    return [p for p in candidates if has_audio(list_archive(p))]


@dataclass
class ArchiveOutcome:
    archive: Path
    status: str  # "ok" | "skipped" | "error"
    destination: Path | None = None
    detail: str = ""
    tracks: int = 0  # kolko audio suborov album obsahuje
    #: Nazov, pod ktorym to prislo v archive — pred upratanim na
    #: "Interpret - Album - Rok". Prazdny, ked sa nemenil.
    povodny: str = ""

    @property
    def album(self) -> str:
        """Nazov albumu tak, ako sa vola vysledny priecinok."""
        return self.destination.name if self.destination else self.archive.stem

    @property
    def premenovany(self) -> bool:
        return bool(self.povodny) and self.povodny != self.album


@dataclass
class ImportResult:
    target: Path
    outcomes: list[ArchiveOutcome] = field(default_factory=list)

    @property
    def extracted(self) -> list[ArchiveOutcome]:
        return [o for o in self.outcomes if o.status == "ok"]

    @property
    def skipped(self) -> list[ArchiveOutcome]:
        return [o for o in self.outcomes if o.status == "skipped"]

    @property
    def failed(self) -> list[ArchiveOutcome]:
        return [o for o in self.outcomes if o.status == "error"]


def count_tracks(folder: Path) -> int:
    """Kolko audio suborov album obsahuje (vratane podpriecinkov, napr. CD1/CD2)."""
    total = 0
    for _root, _dirs, files in os.walk(_long(folder)):
        total += sum(1 for f in files if Path(f).suffix.lower() in AUDIO_EXTENSIONS)
    return total


def extract_archive(archive: Path, destination: Path, dohladat=None) -> ArchiveOutcome:
    """Rozbali jeden archiv do `destination` ako samostatny podpriecinok.

    Rozbaluje sa najprv do docasneho priecinka, aby sme vysledok posudili podla
    skutocnych suborov na disku — nazvy z vypisu archivu mozu byt v inom kodovani.
    Ak archiv obsahuje jediny korenovy priecinok, pouzije sa jeho nazov, inak
    nazov archivu.  Ten sa este uprace na "Interpret - Album - Rok" (`nazvy`).
    Uz existujuci album sa preskoci, nic sa neprepisuje.

    `dohladat` je nepovinna funkcia `nazov -> nazvy.Nazov | None`, ktora sa smie
    spytat aj do siete (zoznam noviniek, Metal Archives). Ma prednost pred
    offline parserom: pozna spravny zapis (`I, Scvlptor`, `Boötes Void`)
    a rozhodne aj tam, kde sa z nazvu uhadnut neda. Ked vrati `None`, plati
    offline parser; ked ani ten, ostane povodny nazov. Modul sam do siete
    nechodi — vdaka tomu je testovatelny bez nej.
    """
    destination.mkdir(parents=True, exist_ok=True)
    # Kratky nazov, aby docasna cesta zbytocne nenafukovala dlzku ciest vnutri.
    tag = hashlib.sha1(archive.name.encode("utf-8", "replace")).hexdigest()[:8]
    staging = destination / f".tmp-{tag}"
    _rmtree(staging)
    staging.mkdir()

    try:
        proc = subprocess.run(
            [str(_TAR), "-xf", str(archive), "-C", str(staging)],
            capture_output=True,
            creationflags=_NO_WINDOW,
        )
        if proc.returncode != 0:
            return ArchiveOutcome(
                archive, "error",
                detail=_decode(proc.stderr).strip().splitlines()[-1] if proc.stderr else "tar zlyhal",
            )

        entries = list(staging.iterdir())
        if not entries:
            return ArchiveOutcome(archive, "error", detail="archiv je prazdny")

        if len(entries) == 1 and entries[0].is_dir():
            source, surovy = entries[0], entries[0].name
        else:
            source, surovy = staging, archive.stem
        album_name = nazvy.uprav(surovy)
        if dohladat is not None:
            try:
                najdene = dohladat(surovy)
            except Exception:  # noqa: BLE001 - vypadok siete nesmie zhodit import
                najdene = None
            if najdene is not None:
                album_name = najdene.text

        # Kontroluje sa aj povodny nazov: albumy rozbalene pred zavedenim
        # upratovania lezia v cieli este pod nim a druhy raz sa rozbalit nemaju.
        for kandidat in (destination / album_name, destination / surovy):
            if os.path.exists(_long(kandidat)):
                return ArchiveOutcome(archive, "skipped", kandidat, "uz existuje",
                                      count_tracks(kandidat), povodny=surovy)

        final = destination / album_name
        os.rename(_long(source), _long(final))
        return ArchiveOutcome(archive, "ok", final, tracks=count_tracks(final),
                              povodny=surovy)
    except OSError as exc:
        return ArchiveOutcome(archive, "error", detail=str(exc))
    finally:
        _rmtree(staging)


def import_from_downloads(
    source: Path | str | None = None,
    root: Path | str | None = None,
    progress=None,
    dohladat=None,
) -> ImportResult:
    """Najde hudobne archivy v Downloads a rozbali ich do priecinka aktualneho roka."""
    destination = target_dir(root)
    archives = find_music_archives(source)
    result = ImportResult(destination)
    for index, archive in enumerate(archives, start=1):
        if progress:
            progress(f"Rozbaľujem {index}/{len(archives)}: {archive.name}")
        result.outcomes.append(extract_archive(archive, destination, dohladat))
    return result


def open_in_explorer(path: Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        subprocess.Popen(["explorer", str(path)], creationflags=_NO_WINDOW)
