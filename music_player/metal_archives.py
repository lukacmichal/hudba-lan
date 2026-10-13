"""Scraper for Encyclopaedia Metallum (metal-archives.com).

Uses curl_cffi to bypass Cloudflare protection by impersonating
a real Chrome TLS fingerprint.

Provides album cover art and song lyrics via the site's internal AJAX endpoints.
"""

from __future__ import annotations

import re
import time
import threading
import unicodedata
from html import unescape

from bs4 import BeautifulSoup
from curl_cffi import requests as cf_requests

BASE_URL = "https://www.metal-archives.com"
_TIMEOUT = 15
_MIN_REQUEST_INTERVAL = 1.5  # seconds between requests

# ── rate limiting ─────────────────────────────────────────────────────────────
_last_request_time = 0.0
_request_lock = threading.Lock()


def _get(url: str, **kwargs) -> cf_requests.Response | None:
    """Rate-limited GET that impersonates Chrome."""
    global _last_request_time
    with _request_lock:
        elapsed = time.time() - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.time()
    try:
        resp = cf_requests.get(url, impersonate="chrome", timeout=_TIMEOUT, **kwargs)
        if resp.status_code == 200:
            return resp
    except Exception:
        pass
    return None


# ── in-memory cache ───────────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_album_cache: dict[str, int | None] = {}   # "artist|||album" -> album_id
_cover_cache: dict[int, str | None] = {}    # album_id -> cover_url
_tracks_cache: dict[int, list[tuple[str, str]]] = {}  # album_id -> [(track_id, title)]
_band_albums_cache: dict[str, list[tuple[int, str, str]]] = {}  # band_lower -> [(album_id, title, type)]
_soup_cache: dict[int, BeautifulSoup] = {}  # album_id -> parsed page (reuse across functions)
_meta_cache: dict[int, dict] = {}           # album_id -> metadata dict


def _key(a: str, b: str) -> str:
    return f"{a.strip().lower()}|||{b.strip().lower()}"


def zabudni_album(artist: str, album: str) -> None:
    """Zahoď všetko, čo si tento beh pamätá o albume a diskografii kapely.

    Volá sa pred opätovným hľadaním textu, ktorý sa minule nenašiel. Stránka
    albumu bez textov nemá ani jedno `lyricsButton…`, takže `_tracks_cache`
    by si „žiadne skladby“ držal do zatvorenia prehrávača — aj keď MA texty
    medzitým doplní.
    """
    with _cache_lock:
        album_id = _album_cache.pop(_key(artist, album), None) if album else None
        if album_id is not None:
            _tracks_cache.pop(album_id, None)
            _soup_cache.pop(album_id, None)
            _cover_cache.pop(album_id, None)
        _band_albums_cache.pop(_normalize_text(artist).strip().lower(), None)


def _clean_album_title(title: str) -> str:
    """Strip common release-type suffixes that don't appear on MA."""
    cleaned = title.strip()
    # Strip surrounding square brackets: [1996-2004] → 1996-2004
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()
    # Strip parenthesised suffixes: (Single), (Remastered), etc.
    cleaned = re.sub(
        r"\s*\((Single|EP|Demo|Remaster(?:ed)?|Deluxe(?:\s+Edition)?|Bonus\s+Track(?:s)?|Digipak|Digipack|Limited\s+Edition|Special\s+Edition|Vinyl|CD|LP|Japanese\s+Edition)\)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    # Strip bare trailing keywords (no parentheses): "Album Remastered" → "Album"
    cleaned = re.sub(
        r"\s+(?:Remaster(?:ed)?|Deluxe(?:\s+Edition)?)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


# ── search ────────────────────────────────────────────────────────────────────


def search_album(artist: str, album: str) -> int | None:
    """Search Metal Archives for an album, return album ID or None."""
    if not artist or not album:
        return None

    key = _key(artist, album)
    with _cache_lock:
        if key in _album_cache:
            return _album_cache[key]

    cleaned_album = _clean_album_title(album)
    search_title = cleaned_album or album

    resp = _get(
        f"{BASE_URL}/search/ajax-advanced/searching/albums/",
        params={
            "bandName": artist,
            "releaseTitle": search_title,
            "sEcho": "1",
            "iDisplayStart": "0",
            "iDisplayLength": "30",
        },
    )
    if resp is None:
        return None

    try:
        rows = resp.json().get("aaData", [])
    except Exception:
        return None

    artist_lower = artist.strip().lower()
    album_lower = _clean_album_title(album).strip().lower() or album.strip().lower()
    best_id = None

    for row in rows:
        album_html = row[1] if len(row) > 1 else ""
        band_html = row[0] if len(row) > 0 else ""

        album_match = re.search(r'href="[^"]+/(\d+)"[^>]*>([^<]+)<', album_html)
        band_match = re.search(r">([^<]+)<", band_html)

        if not album_match:
            continue

        album_id = int(album_match.group(1))
        found_album = unescape(album_match.group(2)).strip().lower()
        found_band = unescape(band_match.group(1)).strip().lower() if band_match else ""

        if found_band == artist_lower and found_album == album_lower:
            best_id = album_id
            break
        # Only accept as fallback if at least the band name matches
        if best_id is None and found_band == artist_lower:
            best_id = album_id

    if best_id is None:
        best_id = _album_z_diskografie(artist, album)

    with _cache_lock:
        _album_cache[key] = best_id

    return best_id


# ── nazov albumu s preklepom ──────────────────────────────────────────────────
# Hladanie na MA berie nazov vydania doslova: jedno zle pismeno a nenajde nic.
# Tagy stiahnutych albumov take preklepy maju — Christ Dismembered vydali
# "Ov Vampiricy", tagy hovoria "Ov Vampiracy" (21. 9. 2026), a prehravac k albumu
# preto nemal ani odkaz na MA, ani obal. Zalozne sa preto prejde diskografia
# kapely a prijme sa nazov, ktory sa lisi najviac jednym pismenom v jednom slove.
# Kratke slova a cisla sa neodpustaju: "Death II" oproti "Death III" alebo
# "Live 2014" oproti "Live 2015" su ine vydania, nie preklep.
_MIN_DLZKA_PREKLEPU = 5


def _slova_nazvu(title: str) -> list[str]:
    """Nazov albumu na porovnanie: slova bez diakritiky, velkych pismen a interpunkcie.

    Apostrof sa zahodi bez medzery, aby "Fool's" a "Fools" bolo to iste slovo.
    """
    text = _normalize_text(_clean_album_title(title)).lower()
    text = re.sub(r"['’`]", "", text)
    return re.findall(r"[^\W_]+", text)


def _jeden_preklep(a: str, b: str) -> bool:
    """Lisia sa slova o jedno pismeno — zamenene, chybajuce, navyse alebo dve prehodene?"""
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    a, b = a[i:], b[i:]
    if len(a) == len(b):
        return a[1:] == b[1:] or (a[:2] == b[1::-1] and a[2:] == b[2:])
    kratsie, dlhsie = sorted((a, b), key=len)
    return kratsie == dlhsie[1:]


def _zhoda_nazvu(nase: list[str], ich: list[str]) -> int:
    """2 = ten isty nazov, 1 = jeden preklep v jednom slove, 0 = iny album."""
    if nase == ich:
        return 2
    if len(nase) != len(ich):
        return 0
    rozdiel = [(a, b) for a, b in zip(nase, ich) if a != b]
    if len(rozdiel) != 1:
        return 0
    a, b = rozdiel[0]
    if min(len(a), len(b)) < _MIN_DLZKA_PREKLEPU or any(c.isdigit() for c in a + b):
        return 0
    return 1 if _jeden_preklep(a, b) else 0


def _album_z_diskografie(artist: str, album: str) -> int | None:
    """Album kapely, ktoreho nazov sa od tagu lisi len zapisom alebo preklepom.

    Preklep sa prijme, iba ked na neho sedi jedine vydanie — pri dvoch sa netipuje.
    """
    nase = _slova_nazvu(album)
    if not nase:
        return None
    preklepy: set[int] = set()
    for album_id, nazov, _typ in _search_band_albums(artist):
        zhoda = _zhoda_nazvu(nase, _slova_nazvu(nazov))
        if zhoda == 2:
            return album_id
        if zhoda == 1:
            preklepy.add(album_id)
    return preklepy.pop() if len(preklepy) == 1 else None


def _normalize_text(text: str) -> str:
    """Normalize unicode chars to ASCII equivalents for MA search.

    e.g. Mediŧation → Meditation, Änglagård → Anglagard
    """
    # NFKD decomposes chars (e.g. ö → o + combining umlaut)
    decomposed = unicodedata.normalize("NFKD", text)
    # Strip combining marks (accents, strokes, etc.)
    ascii_ish = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Handle chars that NFKD doesn't decompose (ŧ→t, đ→d, ł→l, ø→o, etc.)
    extra = str.maketrans("ŧŦđĐłŁøØæÆœŒßþÞ", "tTdDlLoOaAoOstT")
    return ascii_ish.translate(extra)


def _meno_kapely(name: str) -> str:
    return re.sub(r"\s+", " ", _normalize_text(unescape(name))).strip().lower()


def _search_band_albums(artist: str) -> list[tuple[int, str, str]]:
    """Search all albums by a band. Returns [(album_id, album_title, type)].

    MA hlada kapelu podla casti mena — "Dismembered" vrati 82 kapiel od
    Christ Dismembered po Dismembered Pig. Preto sa riadky filtruju na kapelu
    s presne tymto menom (split sa nechava, ked je medzi kapelami). Presnu
    zhodu na strane MA (`exactBandMatch`) pouzit nejde: nerozlisuje diakritiku,
    takze "Bootes Void" by Boötes Void nenasiel.
    """
    artist_normalized = _normalize_text(artist)
    band_lower = artist_normalized.strip().lower()
    with _cache_lock:
        if band_lower in _band_albums_cache:
            return _band_albums_cache[band_lower]

    resp = _get(
        f"{BASE_URL}/search/ajax-advanced/searching/albums/",
        params={
            "bandName": artist_normalized,
            "releaseTitle": "",
            "sEcho": "1",
            "iDisplayStart": "0",
            "iDisplayLength": "200",
        },
    )
    if resp is None:
        return []

    try:
        rows = resp.json().get("aaData", [])
    except Exception:
        return []

    hladana_kapela = _meno_kapely(artist)
    albums: list[tuple[int, str, str]] = []
    for row in rows:
        band_html = row[0] if len(row) > 0 else ""
        kapely = {_meno_kapely(m) for m in re.findall(r">([^<]+)</a>", band_html)}
        if hladana_kapela not in kapely:
            continue
        album_html = row[1] if len(row) > 1 else ""
        typ = unescape(row[2]).strip() if len(row) > 2 else ""
        match = re.search(r'href="[^"]+/(\d+)"[^>]*>([^<]+)<', album_html)
        if match:
            albums.append((int(match.group(1)), unescape(match.group(2)).strip(), typ))

    with _cache_lock:
        _band_albums_cache[band_lower] = albums

    return albums


# ── zalozne hladanie textu naprie kapelou ─────────────────────────────────────
# Ked sa album z tagov na MA nenajde, hlada sa skladba po ostatnych vydaniach
# kapely. Kazde take vydanie je jedna stranka a medzi dopytmi je povinnych
# 1,5 s, takze doslovne "prejdi vsetko" stalo pri Nunslaughteri (240 vydani)
# pat minut na JEDNU skladbu — a stiahli sa hlavne splity a live nahravky.
# Preto strop a poradie podla typu vydania: text piesne byva na riadnom albume,
# nie na kompilacii toho isteho.
_MAX_ZALOZNYCH_ALBUMOV = 25
_PORADIE_TYPOV = {
    "full-length": 0,
    "ep": 1,
    "single": 2,
    "demo": 3,
    "compilation": 4,
    "split": 5,
    "collaboration": 5,
    "live album": 6,
    "video": 7,
    "split video": 7,
    "boxed set": 8,
}
_PORADIE_INE = 9


def _zalozne_albumy(artist: str, uz_skusene: set[int]) -> list[tuple[int, str, str]]:
    """Vydania kapely, ktore este stoji za to stiahnut — v poradi podla typu."""
    zvysok = [a for a in _search_band_albums(artist) if a[0] not in uz_skusene]
    zvysok.sort(key=lambda a: _PORADIE_TYPOV.get(a[2].strip().lower(), _PORADIE_INE))
    return zvysok[:_MAX_ZALOZNYCH_ALBUMOV]


# ── album page parsing ────────────────────────────────────────────────────────


def _fetch_album_page(album_id: int) -> BeautifulSoup | None:
    """Fetch and parse album page HTML. Caches soup for reuse."""
    with _cache_lock:
        if album_id in _soup_cache:
            return _soup_cache[album_id]

    resp = _get(f"{BASE_URL}/albums/_/_/{album_id}")
    if resp is None:
        return None
    soup = BeautifulSoup(resp.text, "lxml")

    with _cache_lock:
        # Keep cache bounded
        if len(_soup_cache) > 10:
            _soup_cache.clear()
        _soup_cache[album_id] = soup

    return soup


def fetch_cover_url(album_id: int) -> str | None:
    """Get album cover image URL."""
    with _cache_lock:
        if album_id in _cover_cache:
            return _cover_cache[album_id]

    soup = _fetch_album_page(album_id)
    if soup is None:
        return None

    # Also parse tracks while we have the page
    _parse_tracks_from_soup(album_id, soup)

    cover_link = soup.find("a", class_="image")
    url = cover_link["href"] if cover_link and cover_link.get("href") else None

    with _cache_lock:
        _cover_cache[album_id] = url

    return url


def _get_album_tracks(album_id: int) -> list[tuple[int, str]]:
    """Get track listing from album page. Returns [(track_id, title)]."""
    with _cache_lock:
        if album_id in _tracks_cache:
            return _tracks_cache[album_id]

    soup = _fetch_album_page(album_id)
    if soup is None:
        return []

    # Also parse cover while we have the page
    cover_link = soup.find("a", class_="image")
    with _cache_lock:
        _cover_cache[album_id] = cover_link["href"] if cover_link and cover_link.get("href") else None

    return _parse_tracks_from_soup(album_id, soup)


def _parse_tracks_from_soup(album_id: int, soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Extract track IDs and titles from album page soup.

    ID skladby NIE JE vzdy cislo: pri vinyloch a splitoch k nemu Metal Archives
    pripaja stranu platne — `lyricsButton8169012B`. Preto sa berie cele a ako
    retazec. Kym sa orezavalo na koncove cislice, taky album nemal ani jednu
    skladbu a text sa k nemu nenasiel nikdy (Nunslaughter - Satanic Chaos
    Legions, 7. 9. 2026). Endpoint s textami zoberie ID aj s pismenom.
    """
    with _cache_lock:
        if album_id in _tracks_cache:
            return _tracks_cache[album_id]

    tracks: list[tuple[str, str]] = []
    for btn in soup.find_all("a", id=re.compile(r"^lyricsButton.")):
        track_id = btn["id"][len("lyricsButton"):].strip()
        if not track_id:
            continue
        tr = btn.find_parent("tr")
        if tr:
            tds = tr.find_all("td")
            title = tds[1].get_text(strip=True) if len(tds) > 1 else ""
            tracks.append((track_id, title))

    with _cache_lock:
        _tracks_cache[album_id] = tracks

    return tracks


# ── lyrics ────────────────────────────────────────────────────────────────────


def _find_track_id(tracks: list[tuple[str, str]], title: str) -> str | None:
    """Match song title to a track ID. Only exact matches to avoid wrong lyrics."""
    title_clean = re.sub(r"^\d+[\.\-\s]+", "", title.strip().lower()).strip()
    if not title_clean:
        return None

    for tid, t in tracks:
        t_clean = re.sub(r"^\d+[\.\-\s]+", "", t.strip().lower()).strip()
        if t_clean == title_clean:
            return tid

    return None


def _fetch_lyrics_by_id(track_id: str) -> str:
    """Download lyrics for a track ID."""
    resp = _get(f"{BASE_URL}/release/ajax-view-lyrics/id/{track_id}")
    if resp is None:
        return ""

    text = resp.text.strip()
    if not text or "(lyrics not available)" in text.lower():
        return ""

    soup = BeautifulSoup(text, "lxml")
    return soup.get_text("\n", strip=True).strip()


# ── public high-level API ─────────────────────────────────────────────────────


def fetch_cover_bytes(artist: str, album: str) -> bytes | None:
    """Search MA for album and download cover art bytes."""
    album_id = search_album(artist, album)
    if album_id is None:
        return None

    cover_url = fetch_cover_url(album_id)
    if not cover_url:
        return None

    resp = _get(cover_url)
    if resp is None or len(resp.content) < 100:
        return None

    return resp.content


def fetch_lyrics(artist: str, title: str, album: str = "") -> str:
    """Search MA for lyrics.

    If album is provided, searches that album directly.
    Otherwise, searches other releases by the artist to find the track.
    """
    if not artist or not title:
        return ""

    skusene: set[int] = set()

    # 1. Try specific album first
    if album:
        album_id = search_album(artist, album)
        if album_id is not None:
            skusene.add(album_id)
            tracks = _get_album_tracks(album_id)
            track_id = _find_track_id(tracks, title)
            if track_id is not None:
                return _fetch_lyrics_by_id(track_id)

    # 2. Ostatne vydania kapely — najviac _MAX_ZALOZNYCH_ALBUMOV, riadne albumy
    #    ako prve. Album z bodu 1 sa uz nesahuje druhy raz.
    for aid, _atitle, _typ in _zalozne_albumy(artist, skusene):
        tracks = _get_album_tracks(aid)
        track_id = _find_track_id(tracks, title)
        if track_id is not None:
            return _fetch_lyrics_by_id(track_id)

    return ""


def fetch_album_metadata(artist: str, album: str) -> dict | None:
    """Fetch extended album metadata from Metal Archives.

    Returns dict with: label, release_date, genre, duration, lineup.
    """
    if not artist or not album:
        return None

    album_id = search_album(artist, album)
    if album_id is None:
        return None

    with _cache_lock:
        if album_id in _meta_cache:
            return _meta_cache[album_id]

    soup = _fetch_album_page(album_id)
    if soup is None:
        return None

    meta = _parse_metadata_from_soup(soup)
    meta["album_url"] = f"{BASE_URL}/albums/_/_/{album_id}"

    with _cache_lock:
        _meta_cache[album_id] = meta

    return meta


def _parse_metadata_from_soup(soup: BeautifulSoup) -> dict:
    """Extract label, release date, genre, duration, lineup from album page."""
    meta: dict = {}

    # Parse <dl> info block
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).rstrip(":")
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        value = re.sub(r"\s+", " ", dd.get_text(strip=True))

        if "label" in label.lower():
            meta["label"] = value
        elif "release date" in label.lower():
            meta["release_date"] = value
        elif "genre" in label.lower():
            meta["genre"] = value
        elif "type" in label.lower():
            meta["type"] = value

    # Total duration — look for the bold total in tracklist
    total_el = soup.find("strong", string=re.compile(r"\d+:\d{2}"))
    if total_el:
        meta["duration"] = total_el.get_text(strip=True)

    # Lineup — only "Band members" category (skip guests, staff)
    lineup: list[dict[str, str]] = []
    for header_row in soup.find_all("tr", class_="lineupHeaders"):
        category = header_row.get_text(strip=True).lower()
        if "band members" not in category:
            continue
        row = header_row.find_next_sibling("tr")
        while row and "lineupHeaders" not in (row.get("class") or []):
            tds = row.find_all("td")
            if len(tds) >= 2:
                name = tds[0].get_text(strip=True)
                role = re.sub(r"\s+", " ", tds[1].get_text(strip=True))
                if name:
                    lineup.append({"name": name, "instrument": role})
            row = row.find_next_sibling("tr")
        break

    if lineup:
        meta["lineup"] = lineup

    return meta
