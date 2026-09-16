"""Tests for NowPlayingServer control + playlist endpoints.

Standalone (pytest in this env is broken):
    python tests/test_control_server.py

No Qt needed — pure http.server.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_player.metadata_server import NowPlayingServer  # noqa: E402


def _make():
    cmds = []
    srv = NowPlayingServer(
        payload_provider=lambda: {"state": "stopped"},
        command_handler=lambda a, p: cmds.append((a, p)),
        playlist_provider=lambda: {"version": 1, "currentIndex": 0, "items": []},
        preferred_port=0,
    )
    srv.start()
    return srv, cmds


def _post(port, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/control",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=3)


def test_health_hlasi_verziu():
    # Verzia v /health je jediny sposob, ako zvonku zistit, co bezi na tom
    # druhom notebooku. Ked z odpovede vypadne, opat sa to neda zistit inak
    # nez sadnut si k nemu.
    from music_player import __version__, __version_code__

    srv, _ = _make()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{srv.port}/health", timeout=3) as odpoved:
            data = json.loads(odpoved.read().decode())
        assert data["status"] == "ok", data
        assert data["version"] == __version__, data
        assert data["versionCode"] == __version_code__, data
    finally:
        srv.stop()


def test_control_valid_action():
    srv, cmds = _make()
    try:
        resp = _post(srv.port, {"action": "next"})
        assert resp.status == 200, resp.status
        assert cmds == [("next", {})], cmds
    finally:
        srv.stop()


def test_control_passes_params():
    srv, cmds = _make()
    try:
        _post(srv.port, {"action": "seek", "positionMs": 5000})
        assert cmds == [("seek", {"positionMs": 5000})], cmds
    finally:
        srv.stop()


def test_control_unknown_action_400():
    srv, cmds = _make()
    try:
        try:
            _post(srv.port, {"action": "bogus"})
            assert False, "expected HTTP 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400, e.code
        assert cmds == [], cmds
    finally:
        srv.stop()


def test_playlist_endpoint():
    srv, _ = _make()
    try:
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{srv.port}/api/playlist", timeout=3
        )
        data = json.loads(resp.read())
        assert data["version"] == 1, data
        assert data["currentIndex"] == 0, data
        assert data["items"] == [], data
    finally:
        srv.stop()


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
