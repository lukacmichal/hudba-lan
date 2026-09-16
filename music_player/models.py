from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".aac",
    ".ogg",
    ".wav",
    ".m4a",
    ".wma",
}


@dataclass(slots=True)
class Track:
    path: str
    title: str
    artist: str = ""
    album: str = ""
    year: str = ""
    duration_ms: int = 0

    @classmethod
    def from_path(cls, path: str) -> "Track":
        resolved = str(Path(path).expanduser().resolve())
        from music_player.tags import read_tags
        t = read_tags(resolved)
        dur = _read_duration_ms(resolved)
        return cls(path=resolved, title=t.title, artist=t.artist, album=t.album, year=t.year, duration_ms=dur)

    @classmethod
    def from_dict(cls, payload: dict) -> "Track":
        path = str(payload.get("path", "")).strip()
        if not path:
            raise ValueError("Track payload is missing path")
        duration_ms = int(payload.get("duration_ms", 0) or 0)
        title = str(payload.get("title", "")).strip()
        artist = str(payload.get("artist", "")).strip()
        album = str(payload.get("album", "")).strip()
        year = str(payload.get("year", "")).strip()
        return cls(path=path, title=title, artist=artist, album=album, year=year, duration_ms=duration_ms)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "duration_ms": self.duration_ms,
        }

    @property
    def duration_display(self) -> str:
        if self.duration_ms <= 0:
            return ""
        total_s = self.duration_ms // 1000
        m, s = divmod(total_s, 60)
        return f"{m}:{s:02d}"

    @property
    def display_text(self) -> str:
        if self.artist:
            return f"{self.artist} – {self.title}"
        return self.title


def _read_duration_ms(path: str) -> int:
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(path)
        if f is not None and f.info and f.info.length:
            return int(f.info.length * 1000)
    except Exception:
        pass
    return 0


def is_audio_file(path: str) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


_PLAYLIST_EXTENSIONS = {".m3u", ".m3u8"}


def _parse_m3u(m3u_path: Path) -> list[str]:
    """Extract audio file paths from an M3U/M3U8 playlist file."""
    base_dir = m3u_path.parent
    entries: list[str] = []
    try:
        text = m3u_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry = Path(line)
        if not entry.is_absolute() and not line.startswith(("\\", "/")):
            # Relative path — resolve against the m3u directory.
            entry = base_dir / entry
        entry = entry.resolve()
        if entry.is_file() and is_audio_file(str(entry)):
            entries.append(str(entry))
    return entries


def collect_audio_paths(paths: list[str]) -> list[str]:
    collected: list[str] = []

    for raw_path in paths:
        candidate = Path(raw_path).expanduser()
        if not candidate.exists():
            continue
        if candidate.is_dir():
            for nested_path in sorted(candidate.rglob("*"), key=lambda item: str(item).lower()):
                if nested_path.is_file() and is_audio_file(str(nested_path)):
                    collected.append(str(nested_path.resolve()))
            continue

        if candidate.is_file() and candidate.suffix.lower() in _PLAYLIST_EXTENSIONS:
            for entry in _parse_m3u(candidate):
                collected.append(entry)
            continue

        if not candidate.is_file() or not is_audio_file(str(candidate)):
            continue

        collected.append(str(candidate.resolve()))

    return collected
