from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from music_player.models import Track
from music_player.zalozky import Zalozka

APP_NAME = "LanMusicPlayer"
STATE_FILE_NAME = "state.json"
DEFAULT_WINDOW_WIDTH = 1000
DEFAULT_WINDOW_HEIGHT = 640


@dataclass(slots=True)
class AppState:
    playlist: list[Track] = field(default_factory=list)
    recent_tracks: list[Track] = field(default_factory=list)
    current_index: int = -1
    position_ms: int = 0
    volume: int = 75
    start_with_windows: bool = False
    shutdown_when_playlist_ends: bool = False
    sleep_when_playlist_ends: bool = False
    output_device_id: str = ""
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    playlist_window_width: int = 700
    playlist_window_height: int = 500
    playlist_window_visible: bool = True
    total_tracks_played: int = 0
    total_listen_ms: int = 0
    scheduled_action: str = "none"
    scheduled_time: str = ""
    zalozky: list[Zalozka] = field(default_factory=list)


class StateStore:
    def __init__(self) -> None:
        self._state_dir = _app_state_dir()
        self._state_file = self._state_dir / STATE_FILE_NAME

    @property
    def state_file(self) -> Path:
        return self._state_file

    def load(self) -> AppState:
        if not self._state_file.exists():
            return AppState()
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppState()

        playlist = _deserialize_tracks(payload.get("playlist", []))
        recent_tracks = _deserialize_tracks(payload.get("recent_tracks", []))
        current_index = int(payload.get("current_index", -1))
        volume = _clamp_int(payload.get("volume", 75), 0, 100, 75)
        position_ms = max(int(payload.get("position_ms", 0)), 0)
        width = _clamp_int(payload.get("window_width", DEFAULT_WINDOW_WIDTH), 400, 2400, DEFAULT_WINDOW_WIDTH)
        height = _clamp_int(payload.get("window_height", DEFAULT_WINDOW_HEIGHT), 100, 1600, DEFAULT_WINDOW_HEIGHT)
        pl_width = _clamp_int(payload.get("playlist_window_width", 700), 400, 2400, 700)
        pl_height = _clamp_int(payload.get("playlist_window_height", 500), 300, 1600, 500)
        pl_visible = bool(payload.get("playlist_window_visible", True))

        if not playlist:
            current_index = -1
            position_ms = 0
        elif current_index < 0 or current_index >= len(playlist):
            current_index = 0
            position_ms = 0

        return AppState(
            playlist=playlist,
            recent_tracks=recent_tracks,
            current_index=current_index,
            position_ms=position_ms,
            volume=volume,
            start_with_windows=bool(payload.get("start_with_windows", False)),
            shutdown_when_playlist_ends=bool(payload.get("shutdown_when_playlist_ends", False)),
            sleep_when_playlist_ends=bool(payload.get("sleep_when_playlist_ends", False)),
            output_device_id=str(payload.get("output_device_id", "")).strip(),
            window_width=width,
            window_height=height,
            playlist_window_width=pl_width,
            playlist_window_height=pl_height,
            playlist_window_visible=pl_visible,
            total_tracks_played=max(int(payload.get("total_tracks_played", 0)), 0),
            total_listen_ms=max(int(payload.get("total_listen_ms", 0)), 0),
            scheduled_action=str(payload.get("scheduled_action", "none")),
            scheduled_time=str(payload.get("scheduled_time", "")),
            zalozky=_deserialize_zalozky(payload.get("zalozky", [])),
        )

    def save(self, state: AppState) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "playlist": [track.to_dict() for track in state.playlist],
            "recent_tracks": [track.to_dict() for track in state.recent_tracks],
            "current_index": state.current_index,
            "position_ms": max(int(state.position_ms), 0),
            "volume": _clamp_int(state.volume, 0, 100, 75),
            "start_with_windows": bool(state.start_with_windows),
            "shutdown_when_playlist_ends": bool(state.shutdown_when_playlist_ends),
            "sleep_when_playlist_ends": bool(state.sleep_when_playlist_ends),
            "output_device_id": str(state.output_device_id or ""),
            "window_width": _clamp_int(state.window_width, 400, 2400, DEFAULT_WINDOW_WIDTH),
            "window_height": _clamp_int(state.window_height, 100, 1600, DEFAULT_WINDOW_HEIGHT),
            "playlist_window_width": _clamp_int(state.playlist_window_width, 400, 2400, 700),
            "playlist_window_height": _clamp_int(state.playlist_window_height, 300, 1600, 500),
            "playlist_window_visible": bool(state.playlist_window_visible),
            "total_tracks_played": max(int(state.total_tracks_played), 0),
            "total_listen_ms": max(int(state.total_listen_ms), 0),
            "scheduled_action": state.scheduled_action,
            "scheduled_time": state.scheduled_time,
            "zalozky": [zalozka.to_dict() for zalozka in state.zalozky],
        }
        temp_file = self._state_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        temp_file.replace(self._state_file)


def _app_state_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def _deserialize_tracks(items: list[dict]) -> list[Track]:
    tracks: list[Track] = []
    for item in items:
        try:
            track = Track.from_dict(item)
        except (TypeError, ValueError):
            continue
        tracks.append(track)
    return tracks


def _deserialize_zalozky(items) -> list[Zalozka]:
    if not isinstance(items, list):
        return []
    zalozky: list[Zalozka] = []
    for item in items:
        try:
            zalozky.append(Zalozka.from_dict(item))
        except (AttributeError, TypeError, ValueError):
            continue
    return zalozky


def _clamp_int(value: int, minimum: int, maximum: int, fallback: int) -> int:
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, numeric_value))
