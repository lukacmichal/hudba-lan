"""Tests for PlayerController.playlist_payload() and playlistVersion bumping.

Standalone (pytest in this env is broken):
    python tests/test_playlist_payload.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from music_player import models  # noqa: E402
from music_player import player_controller as pc  # noqa: E402
from music_player.models import Track  # noqa: E402
from music_player.player_controller import PlayerController  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _track(tag: str) -> Track:
    return Track(path=fr"C:\music\{tag}.mp3", title=tag, artist=f"art{tag}", duration_ms=1000)


def test_payload_shape():
    c = PlayerController()
    c.playlist = [_track("A"), _track("B")]
    c.current_index = 1
    p = c.playlist_payload()
    assert set(p.keys()) == {"version", "currentIndex", "items"}, p.keys()
    assert p["currentIndex"] == 1
    assert len(p["items"]) == 2
    it = p["items"][0]
    assert it["index"] == 0, it
    assert it["title"] == "A", it
    assert it["artist"] == "artA", it
    assert it["durationMs"] == 1000, it


def test_version_in_snapshot():
    c = PlayerController()
    assert "playlistVersion" in c.snapshot()


def test_version_bumps_on_content_change():
    c = PlayerController()
    c.playlist = [_track("A"), _track("B"), _track("C")]
    v0 = c.playlist_payload()["version"]
    c.remove_indices([0])
    v1 = c.playlist_payload()["version"]
    assert v1 > v0, (v0, v1)
    c.move_indices([0], 2)
    v2 = c.playlist_payload()["version"]
    assert v2 > v1, (v1, v2)
    c.clear_playlist()
    v3 = c.playlist_payload()["version"]
    assert v3 > v2, (v2, v3)


def test_version_bumps_on_add():
    c = PlayerController()
    orig_collect = pc.collect_audio_paths
    orig_from = models.Track.__dict__["from_path"]
    pc.collect_audio_paths = lambda paths: ["a.mp3"]
    models.Track.from_path = classmethod(lambda cls, path: _track("A"))
    try:
        v0 = c.playlist_payload()["version"]
        c.add_paths(["whatever"])
        assert c.playlist_payload()["version"] > v0
    finally:
        pc.collect_audio_paths = orig_collect
        models.Track.from_path = orig_from


def test_version_stable_on_navigation():
    c = PlayerController()
    c.playlist = [_track("A"), _track("B")]
    c.current_index = 0
    v = c.playlist_payload()["version"]
    c.next_track()  # changes current_index, NOT content
    assert c.playlist_payload()["version"] == v, "navigation must not bump version"


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
