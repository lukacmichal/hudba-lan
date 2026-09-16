"""Tests for the scheduled sleep/shutdown timer (next-occurrence semantics).

Standalone (pytest in this env is broken):
    python tests/test_scheduled_timer.py
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from music_player import player_controller as pc  # noqa: E402
from music_player.player_controller import PlayerController  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _hhmm(dt: datetime) -> str:
    return f"{dt.hour:02d}:{dt.minute:02d}"


def test_next_occurrence_future_is_today():
    future = datetime.now() + timedelta(hours=1)
    target = PlayerController._next_occurrence(_hhmm(future))
    assert target.date() == future.date(), target
    assert target > datetime.now(), target


def test_next_occurrence_past_rolls_to_tomorrow():
    past = datetime.now() - timedelta(hours=1)
    target = PlayerController._next_occurrence(_hhmm(past))
    assert target > datetime.now(), target
    assert target - datetime.now() < timedelta(days=1), target


def test_past_midnight_time_keeps_timer_running():
    """Regression: a time earlier than now used to be silently dropped while
    the UI still claimed the action was scheduled."""
    c = PlayerController()
    c.scheduled_time = _hhmm(datetime.now() - timedelta(minutes=30))
    c.set_scheduled_action("sleep")
    assert c._scheduled_timer.isActive(), "timer must run for a tomorrow target"
    assert c._scheduled_target is not None
    assert c._scheduled_target > datetime.now()


def test_status_mentions_format_and_tomorrow():
    c = PlayerController()
    got = []
    c.scheduled_status_changed.connect(got.append)
    c.scheduled_time = _hhmm(datetime.now() - timedelta(minutes=30))
    c.set_scheduled_action("sleep")
    assert got, "status must be emitted"
    assert "hodiny:minúty" in got[-1], got[-1]
    # 30 min ago normally rolls to tomorrow; right after midnight it may
    # still be today — assert consistency with the computed target instead.
    expect_tomorrow = c._scheduled_target.date() != datetime.now().date()
    assert ("zajtra" in got[-1]) == expect_tomorrow, got[-1]


def test_tick_executes_within_grace():
    c = PlayerController()
    fired = []
    orig = pc.sleep_windows
    pc.sleep_windows = lambda: fired.append(True)
    try:
        c.scheduled_time = _hhmm(datetime.now() + timedelta(hours=1))
        c.set_scheduled_action("sleep")
        # Simulate the clock reaching the target a few seconds ago.
        c._scheduled_target = datetime.now() - timedelta(seconds=5)
        c._on_scheduled_timer_tick()
        assert fired == [True], fired
    finally:
        pc.sleep_windows = orig


def test_tick_cancels_when_target_long_past():
    """Missed moment (PC slept through it) must cancel, not fire on wake."""
    c = PlayerController()
    fired = []
    orig = pc.shutdown_windows
    pc.shutdown_windows = lambda: fired.append(True)
    try:
        c.scheduled_time = _hhmm(datetime.now() + timedelta(hours=1))
        c.set_scheduled_action("shutdown")
        c._scheduled_target = datetime.now() - timedelta(hours=5)
        c._on_scheduled_timer_tick()
        assert fired == [], fired
        assert c.scheduled_action == "none"
        assert not c._scheduled_timer.isActive()
    finally:
        pc.shutdown_windows = orig


def test_tick_before_target_is_noop():
    c = PlayerController()
    fired = []
    orig = pc.sleep_windows
    pc.sleep_windows = lambda: fired.append(True)
    try:
        c.scheduled_time = _hhmm(datetime.now() + timedelta(hours=2))
        c.set_scheduled_action("sleep")
        c._on_scheduled_timer_tick()
        assert fired == [], fired
        assert c.scheduled_action == "sleep"
        assert c._scheduled_timer.isActive()
    finally:
        pc.sleep_windows = orig


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
