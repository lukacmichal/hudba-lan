"""Tests for PlayerController.handle_remote_command() dispatch.

Standalone (pytest in this env is broken):
    python tests/test_remote_command.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from music_player import player_controller as pc  # noqa: E402
from music_player.player_controller import PlayerController  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _spy(c):
    calls = []
    for name in ("toggle_playback", "stop", "next_track", "previous_track"):
        setattr(c, name, (lambda *a, n=name: calls.append(n)))
    c.seek = lambda ms: calls.append(("seek", ms))
    c.play_track_at = lambda i: calls.append(("idx", i))
    return calls


def test_dispatch_order():
    c = PlayerController()
    calls = _spy(c)
    c.handle_remote_command("playpause", {})
    c.handle_remote_command("stop", {})
    c.handle_remote_command("next", {})
    c.handle_remote_command("prev", {})
    c.handle_remote_command("seek", {"positionMs": 1234})
    c.handle_remote_command("playIndex", {"index": 3})
    assert calls == [
        "toggle_playback", "stop", "next_track", "previous_track",
        ("seek", 1234), ("idx", 3),
    ], calls


def test_unknown_action_is_noop():
    c = PlayerController()
    _spy(c)
    c.handle_remote_command("bogus", {})  # must not raise


def test_seek_bad_param_is_noop():
    c = PlayerController()
    calls = _spy(c)
    c.handle_remote_command("seek", {})           # missing -> defaults 0
    c.handle_remote_command("seek", {"positionMs": "nope"})  # invalid -> swallowed
    assert calls == [("seek", 0)], calls


def test_shutdown_calls_system(monkeypatch=None):
    c = PlayerController()
    fired = []
    orig = pc.shutdown_windows
    pc.shutdown_windows = lambda: fired.append(True)
    try:
        c.handle_remote_command("shutdown", {})
        assert fired == [True], fired
    finally:
        pc.shutdown_windows = orig


def test_sleep_calls_system():
    c = PlayerController()
    fired = []
    orig = pc.sleep_windows
    pc.sleep_windows = lambda: fired.append(True)
    try:
        c.handle_remote_command("sleep", {})
        assert fired == [True], fired
        # sleep must NOT latch the power guard (process survives suspend)
        assert c._power_action_in_progress is False
    finally:
        pc.sleep_windows = orig


def test_spanok_jumps_to_tail():
    """"Spanok" z widgetu je ten isty skok ako tlacidlo na PC.

    Podstatne je, ze pocitac NEUSPAVA — o to sa stara "Vypnut/Spat po skonceni".
    Keby sa sem raz pridalo uspanie, tlacidlo by cez den zhaslo notebook.
    """
    c = PlayerController()
    fired = []
    c.jump_to_sleep_tail = lambda: fired.append(True) or 0
    usnute = []
    orig_sleep, orig_shutdown = pc.sleep_windows, pc.shutdown_windows
    pc.sleep_windows = lambda: usnute.append("sleep")
    pc.shutdown_windows = lambda: usnute.append("shutdown")
    try:
        c.handle_remote_command("spanok", {})
        assert fired == [True], fired
        assert usnute == [], usnute
    finally:
        pc.sleep_windows, pc.shutdown_windows = orig_sleep, orig_shutdown


def test_spanok_is_allowed_by_api():
    """Dispatcher aj whitelist musia poznat tu istu akciu.

    Bez tohto by sa dala vetva v dispatcheri pridat a server by prikaz aj tak
    zahodil este pred nou — tichy vypadok, ktory sa hlada zle.
    """
    from music_player.metadata_server import _ALLOWED_ACTIONS
    assert "spanok" in _ALLOWED_ACTIONS


def test_set_volume():
    c = PlayerController()
    got = []
    c.set_volume = lambda v: got.append(v)
    c.handle_remote_command("setVolume", {"value": 42})
    assert got == [42], got


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
