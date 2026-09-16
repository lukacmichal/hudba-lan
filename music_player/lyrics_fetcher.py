from __future__ import annotations

import threading
from typing import Callable


def fetch_lyrics_async(
    artist: str,
    title: str,
    callback: Callable[[str], None],
) -> None:
    """Fetch lyrics in a background thread, then invoke callback on the result."""

    def _run() -> None:
        lyrics = _fetch(artist.strip(), title.strip())
        callback(lyrics)

    threading.Thread(target=_run, daemon=True).start()


def _fetch(artist: str, title: str) -> str:
    if not artist or not title:
        return ""
    try:
        import requests  # type: ignore[import]

        resp = requests.get(
            f"https://api.lyrics.ovh/v1/{_quote(artist)}/{_quote(title)}",
            timeout=6,
        )
        if resp.status_code == 200:
            return resp.json().get("lyrics", "").strip()
    except Exception:
        pass
    return ""


def _quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")
