"""Fetch album cover art, lyrics, and metadata from web sources.

Cover art chain:  disk cache → Metal Archives → Deezer → embedded tags (fallback in UI)
Lyrics chain:     disk cache → Metal Archives → LRCLIB
Metadata chain:   disk cache → Metal Archives

All functions are blocking and meant to be called from background threads.
Results are persisted to disk alongside the music files.
"""

from __future__ import annotations

import threading

import requests

_HEADERS = {"User-Agent": "LanMusicPlayer/1.0"}
_TIMEOUT = 10

# ── simple in-memory cache ────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cover_cache: dict[str, bytes | None] = {}  # "artist|||album" → image bytes
_lyrics_cache: dict[str, str | None] = {}   # "artist|||title" → lyrics text (None = not yet cached)


def _key(a: str, b: str) -> str:
    return f"{a.strip().lower()}|||{b.strip().lower()}"


# ── cover art ─────────────────────────────────────────────────────────────────


def fetch_cover(artist: str, album: str, track_path: str = "") -> bytes | None:
    """Try to fetch album cover art. Disk cache → MA → Deezer."""
    if not artist or not album:
        return None

    key = _key(artist, album)
    with _cache_lock:
        if key in _cover_cache:
            return _cover_cache[key]

    # 1. Disk cache
    if track_path:
        from music_player.disk_cache import read_cached_cover
        data = read_cached_cover(track_path)
        if data:
            with _cache_lock:
                _cover_cache[key] = data
            return data

    # Clean album title for searches
    from music_player.metal_archives import _clean_album_title
    cleaned_album = _clean_album_title(album) or album

    # 2. Metal Archives (primary web source)
    data = _cover_from_metal_archives(artist, cleaned_album)

    # 3. Deezer (fallback)
    if not data:
        data = _cover_from_deezer(artist, cleaned_album)

    # Persist to disk
    if data and track_path:
        from music_player.disk_cache import write_cached_cover
        write_cached_cover(track_path, data)

    with _cache_lock:
        _cover_cache[key] = data
    return data


def _cover_from_metal_archives(artist: str, album: str) -> bytes | None:
    try:
        from music_player.metal_archives import fetch_cover_bytes
        return fetch_cover_bytes(artist, album)
    except Exception:
        return None


def _cover_from_deezer(artist: str, album: str) -> bytes | None:
    try:
        resp = requests.get(
            "https://api.deezer.com/search/album",
            params={"q": f'artist:"{artist}" album:"{album}"', "limit": "5"},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return None

        albums = resp.json().get("data", [])
        if not albums:
            resp = requests.get(
                "https://api.deezer.com/search/album",
                params={"q": f"{artist} {album}", "limit": "5"},
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            albums = resp.json().get("data", [])

        if not albums:
            return None

        cover_url = None
        artist_lower = artist.strip().lower()
        album_lower = album.strip().lower()

        for a in albums:
            a_artist = (a.get("artist", {}).get("name") or "").lower()
            a_title = (a.get("title") or "").lower()
            if a_artist == artist_lower and a_title == album_lower:
                cover_url = a.get("cover_big") or a.get("cover_xl") or a.get("cover_medium")
                break

        # Fallback: only accept first result if artist name matches
        if cover_url is None and albums:
            a = albums[0]
            a_artist = (a.get("artist", {}).get("name") or "").lower()
            if a_artist == artist_lower:
                cover_url = a.get("cover_big") or a.get("cover_xl") or a.get("cover_medium")

        if not cover_url:
            return None

        img_resp = requests.get(cover_url, headers=_HEADERS, timeout=_TIMEOUT)
        if img_resp.status_code == 200 and len(img_resp.content) > 100:
            return img_resp.content
    except Exception:
        pass
    return None


# ── lyrics ────────────────────────────────────────────────────────────────────


def fetch_lyrics(artist: str, title: str, album: str = "", track_path: str = "",
                 vynutit: bool = False) -> str:
    """Try to fetch lyrics. Disk cache → MA → LRCLIB.

    `vynutit` (tlačidlo „Načítať texty“) obíde pamäť aj disk a spýta sa MA
    hneď. Nájdený text z disku ale neprepíše prázdnym výsledkom — MA môže
    práve neodpovedať.
    """
    if not artist or not title:
        return ""

    # V pamäti len nájdené texty. „Nenašlo sa“ by tu inak platilo do zatvorenia
    # prehrávača (čiže dni), aj keď ho MA medzitým doplní; o jeho platnosti
    # rozhoduje značka na disku.
    key = _key(artist, title)
    with _cache_lock:
        if not vynutit and _lyrics_cache.get(key):
            return _lyrics_cache[key]

    predtym = ""
    if vynutit:
        _forget_metal_archives(artist, album)
        if track_path:
            from music_player.disk_cache import read_cached_lyrics, zabudni_nenaslo_albumu
            predtym = read_cached_lyrics(track_path, title) or ""
            zabudni_nenaslo_albumu(track_path)

    # 1. Disk cache
    if track_path and not vynutit:
        from music_player.disk_cache import ma_znacku_nenaslo, read_cached_lyrics
        cached = read_cached_lyrics(track_path, title)
        if cached is not None:
            # cached == "" means "searched recently, not found" (sentinel)
            if cached:
                with _cache_lock:
                    _lyrics_cache[key] = cached
            return cached
        if ma_znacku_nenaslo(track_path, title):
            # Stará značka → hľadá sa znova. MA si v pamäti drží „album bez
            # textov“ z minulého hľadania, to treba zabudnúť, inak sa nič nezmení.
            _forget_metal_archives(artist, album)

    # 2. Metal Archives (only source)
    text = _lyrics_from_metal_archives(artist, title, album)

    if vynutit and predtym and not text:
        return predtym
    if vynutit and predtym and text != predtym and track_path:
        from music_player.disk_cache import zmaz_preklad
        zmaz_preklad(track_path, title)

    # Persist to disk (including empty = sentinel)
    if track_path:
        from music_player.disk_cache import write_cached_lyrics
        write_cached_lyrics(track_path, title, text)

    if text:
        with _cache_lock:
            _lyrics_cache[key] = text
    return text


def _forget_metal_archives(artist: str, album: str) -> None:
    try:
        from music_player.metal_archives import zabudni_album
        zabudni_album(artist, album)
    except Exception:
        pass


def _lyrics_from_metal_archives(artist: str, title: str, album: str) -> str:
    try:
        from music_player.metal_archives import fetch_lyrics
        return fetch_lyrics(artist, title, album)
    except Exception:
        return ""


def _lyrics_from_lrclib(artist: str, title: str) -> str:
    try:
        resp = requests.get(
            "https://lrclib.net/api/search",
            params={"artist_name": artist, "track_name": title},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return ""

        results = resp.json()
        if not results:
            return ""

        artist_lower = artist.strip().lower()
        title_lower = title.strip().lower()

        for r in results:
            r_artist = (r.get("artistName") or "").lower()
            r_title = (r.get("trackName") or "").lower()
            if r_artist == artist_lower and r_title == title_lower:
                return (r.get("plainLyrics") or "").strip()

        return ""
    except Exception:
        return ""


# ── album metadata ────────────────────────────────────────────────────────────


def fetch_album_metadata(artist: str, album: str, track_path: str = "") -> dict | None:
    """Fetch extended album metadata. Disk cache → MA."""
    if not artist or not album:
        return None

    # 1. Disk cache
    if track_path:
        from music_player.disk_cache import read_cached_album_meta, write_cached_album_meta
        cached = read_cached_album_meta(track_path)
        if cached is not None:
            if "album_url" not in cached:
                patched = _patch_album_url(cached, artist, album)
                if "album_url" in patched:
                    write_cached_album_meta(track_path, patched)
                    return patched
                # Patch failed — fall through to fresh MA fetch below
            else:
                return cached

    # 2. Metal Archives
    meta = None
    try:
        from music_player.metal_archives import fetch_album_metadata
        meta = fetch_album_metadata(artist, album)
    except Exception:
        pass

    # Persist to disk
    if meta and track_path:
        from music_player.disk_cache import write_cached_album_meta
        write_cached_album_meta(track_path, meta)

    return meta


def _patch_album_url(meta: dict, artist: str, album: str) -> dict:
    """Add album_url to cached metadata that predates the field."""
    try:
        from music_player.metal_archives import search_album, BASE_URL
        album_id = search_album(artist, album)
        if album_id:
            meta = dict(meta)
            meta["album_url"] = f"{BASE_URL}/albums/_/_/{album_id}"
    except Exception:
        pass
    return meta
