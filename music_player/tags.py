from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TrackTags:
    title: str
    artist: str
    album: str
    year: str
    cover_data: bytes | None  # raw image bytes (JPEG or PNG)
    album_artist: str = ""
    genre: str = ""
    track_number: str = ""
    disc_number: str = ""
    composer: str = ""
    comment: str = ""


def read_tags(path: str) -> TrackTags:
    """Read ID3/FLAC/MP4 tags. Falls back to filename parsing if mutagen unavailable."""
    try:
        from mutagen import File as MutagenFile  # type: ignore[import]

        f = MutagenFile(path, easy=True)
        if f is not None:
            title = _first(f.get("title")) or ""
            artist = _first(f.get("artist")) or ""
            album_artist = _first(f.get("albumartist")) or ""
            album = _first(f.get("album")) or ""
            year = (_first(f.get("date")) or _first(f.get("year")) or "")[:4]
            genre = _first(f.get("genre")) or ""
            track_number = _first(f.get("tracknumber")) or ""
            disc_number = _first(f.get("discnumber")) or ""
            composer = _first(f.get("composer")) or ""
            comment = _first(f.get("comment")) or ""
            if not artist and album_artist:
                artist = album_artist
            if not title:
                title, parsed_artist = _parse_filename(path)
                if not artist:
                    artist = parsed_artist
            return TrackTags(
                title=title,
                artist=artist,
                album=album,
                year=year,
                cover_data=_extract_cover(path),
                album_artist=album_artist,
                genre=genre,
                track_number=track_number,
                disc_number=disc_number,
                composer=composer,
                comment=comment,
            )
    except Exception:
        pass
    title, artist = _parse_filename(path)
    return TrackTags(title=title, artist=artist, album="", year="", cover_data=None)


def write_tags(
    path: str,
    *,
    title: str = "",
    artist: str = "",
    album: str = "",
    year: str = "",
    album_artist: str = "",
    genre: str = "",
    track_number: str = "",
    disc_number: str = "",
    composer: str = "",
    comment: str = "",
) -> bool:
    """Write ID3/FLAC/MP4 tags back to file. Returns True on success."""
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(path, easy=True)
        if f is None:
            return False
        _set_or_del(f, "title", title)
        _set_or_del(f, "artist", artist)
        _set_or_del(f, "album", album)
        _set_or_del(f, "date", year)
        _set_or_del(f, "albumartist", album_artist)
        _set_or_del(f, "genre", genre)
        _set_or_del(f, "tracknumber", track_number)
        _set_or_del(f, "discnumber", disc_number)
        _set_or_del(f, "composer", composer)
        _set_or_del(f, "comment", comment)
        f.save()
        return True
    except Exception:
        return False


def _set_or_del(f, key: str, value: str) -> None:
    if value:
        f[key] = value
    elif key in f:
        del f[key]


def _first(value: object) -> str | None:
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value else None


def _parse_filename(path: str) -> tuple[str, str]:
    stem = Path(path).stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip() or stem, artist.strip()
    return stem, ""


def _extract_cover(path: str) -> bytes | None:
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".mp3" or suffix in {".wav", ".aiff"}:
            from mutagen.id3 import ID3  # type: ignore[import]
            tags = ID3(path)
            for key in tags.keys():
                if key.startswith("APIC"):
                    return bytes(tags[key].data)
        if suffix == ".flac":
            from mutagen.flac import FLAC  # type: ignore[import]
            f = FLAC(path)
            if f.pictures:
                return bytes(f.pictures[0].data)
        if suffix in {".m4a", ".aac", ".mp4"}:
            from mutagen.mp4 import MP4  # type: ignore[import]
            f = MP4(path)
            covers = (f.tags or {}).get("covr", [])
            if covers:
                return bytes(covers[0])
        if suffix in {".ogg", ".opus"}:
            import base64
            from mutagen.oggvorbis import OggVorbis  # type: ignore[import]
            from mutagen.flac import Picture  # type: ignore[import]
            f = OggVorbis(path)
            pics = f.get("metadata_block_picture", [])
            if pics:
                pic = Picture(base64.b64decode(pics[0]))
                return bytes(pic.data)
        if suffix == ".wma":
            from mutagen.asf import ASF  # type: ignore[import]
            f = ASF(path)
            pics = f.tags.get("WM/Picture", [])
            if pics:
                return bytes(pics[0].value)
    except Exception:
        pass
    # Generic fallback: try ID3 on anything
    try:
        from mutagen.id3 import ID3  # type: ignore[import]
        tags = ID3(path)
        for key in tags.keys():
            if key.startswith("APIC"):
                return bytes(tags[key].data)
    except Exception:
        pass
    return None
