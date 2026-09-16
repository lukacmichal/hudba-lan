"""Regression tests for PlayerController.move_indices with duplicate tracks.

Bug (2026-06-18): reordering the playlist while a track that has an earlier
duplicate was playing snapped current_index back to the *first* occurrence of
that file.  Playback then replayed the rest of the playlist and "shutdown when
playlist ends" never fired, so the PC ran all night.

Root cause: current_index was restored by matching track *path* (first match
wins) instead of the exact Track object.  Fixed by restoring via identity.

Runnable two ways:
    python tests/test_move_indices_duplicates.py      # standalone
    pytest tests/test_move_indices_duplicates.py       # if pytest works
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from music_player.models import Track  # noqa: E402
from music_player.player_controller import PlayerController  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _track(tag: str) -> Track:
    """A distinct Track object each call (duplicates share a path, not identity)."""
    return Track(path=fr"C:\music\{tag}.mp3", title=tag)


def test_reorder_keeps_current_on_the_same_duplicate():
    c = PlayerController()
    x_first, y, x_last = _track("X"), _track("Y"), _track("X")
    c.playlist = [x_first, y, x_last]
    c.current_index = 2  # playing the *last* X

    c.move_indices([1], 3)  # drag Y to the end

    assert c.playlist[c.current_index] is x_last
    assert c.playlist[c.current_index] is not x_first


def test_last_two_songs_setup_not_snapped_to_first_occurrence():
    # 0:A 1:I4(dup) 2:V(dup) 3:B 4:I4 5:V  — the two real "last songs" are 4 and 5,
    # but the same files also appear earlier at 1 and 2.
    c = PlayerController()
    a, i4_dup, v_dup, b, i4, v = (
        _track("A"), _track("I4"), _track("V"), _track("B"), _track("I4"), _track("V")
    )
    c.playlist = [a, i4_dup, v_dup, b, i4, v]
    c.current_index = 4  # playing the last I4

    c.move_indices([3], 6)  # reorder: push B to the end

    playing = c.playlist[c.current_index]
    assert playing is i4
    assert playing is not i4_dup
    assert c.current_index != 1  # must not jump back to the early duplicate


def test_moving_the_playing_track_follows_it():
    c = PlayerController()
    p, q, r = _track("P"), _track("Q"), _track("R")
    c.playlist = [p, q, r]
    c.current_index = 0  # playing P

    c.move_indices([0], 3)  # drag the playing track itself to the end

    assert c.playlist[c.current_index] is p


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
    sys.exit(1 if failures else 0)
