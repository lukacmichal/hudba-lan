"""Tests for listen-time / play-count accounting in PlayerController.

The stats are accumulated from playback-position deltas (robust to gapless
swaps, skips, seeks and pipeline recreation) rather than wall-clock sessions.

Standalone (pytest in this env is broken):
    python tests/test_listen_stats.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402

from music_player.player_controller import PlayerController  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakePlayer:
    """Minimal stand-in so we can drive _on_position_changed deterministically."""

    def __init__(self, duration_ms=200_000):
        self._state = QMediaPlayer.PlaybackState.PlayingState
        self._duration = duration_ms
        self._position = 0

    def playbackState(self):
        return self._state

    def duration(self):
        return self._duration

    def position(self):
        return self._position


def _make():
    c = PlayerController()
    # Isolate the accounting logic from Qt/audio side effects.
    c._refresh_snapshot = lambda: None
    c._preload_next_track = lambda: None
    c.player = _FakePlayer()
    c.total_listen_ms = 0
    c.total_tracks_played = 0
    c._reset_track_accounting()  # baseline + per-track flag
    return c


def _advance(c, *positions):
    for p in positions:
        c.player._position = p
        c._on_position_changed(p)


def test_listen_time_counts_position_deltas():
    c = _make()
    _advance(c, 0, 1000, 2000, 3000)
    assert c.total_listen_ms == 3000, c.total_listen_ms


def test_seek_forward_not_counted():
    c = _make()
    _advance(c, 0, 1000, 2000)            # +2000
    _advance(c, 100_000)                  # big jump (seek) -> ignored
    _advance(c, 101_000, 102_000)         # +2000
    assert c.total_listen_ms == 4000, c.total_listen_ms


def test_seek_backward_not_double_jumped():
    c = _make()
    _advance(c, 0, 50_000)               # jump from 0->50000 ignored (too big)
    _advance(c, 51_000)                  # +1000
    _advance(c, 1_000)                   # backward jump -> ignored
    _advance(c, 2_000)                   # +1000
    assert c.total_listen_ms == 2000, c.total_listen_ms


def test_track_change_reset_not_counted():
    c = _make()
    _advance(c, 0, 1000, 2000)           # +2000 on track A
    c._reset_track_accounting()          # new track loaded
    _advance(c, 0, 1000)                 # track B: +1000 (0->1000)
    assert c.total_listen_ms == 3000, c.total_listen_ms


def test_play_count_increments_after_threshold():
    c = _make()  # duration 200_000 -> threshold = min(30000, 60000) = 30000
    _advance(c, 0, 10_000, 29_000)
    assert c.total_tracks_played == 0, c.total_tracks_played
    _advance(c, 30_000)
    assert c.total_tracks_played == 1, c.total_tracks_played


def test_play_count_only_once_per_track():
    c = _make()
    _advance(c, 30_000, 60_000, 120_000, 199_000)
    assert c.total_tracks_played == 1, c.total_tracks_played


def test_play_count_resets_per_track():
    c = _make()
    _advance(c, 30_000)
    assert c.total_tracks_played == 1
    c._reset_track_accounting()
    _advance(c, 0, 30_000)
    assert c.total_tracks_played == 2, c.total_tracks_played


def test_short_track_uses_percentage_threshold():
    c = _make()
    c.player._duration = 60_000           # 30% = 18_000 < 30_000
    _advance(c, 17_000)
    assert c.total_tracks_played == 0
    _advance(c, 18_000)
    assert c.total_tracks_played == 1, c.total_tracks_played


def test_no_count_when_not_playing():
    c = _make()
    c.player._state = QMediaPlayer.PlaybackState.PausedState
    _advance(c, 0, 1000, 2000, 30_000)
    assert c.total_listen_ms == 0, c.total_listen_ms
    assert c.total_tracks_played == 0, c.total_tracks_played


def test_effective_listen_ms_returns_total():
    c = _make()
    _advance(c, 0, 1000, 2000)
    assert c._effective_listen_ms() == c.total_listen_ms == 2000


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {type(exc).__name__}: {exc}")
    sys.exit(1 if failures else 0)
