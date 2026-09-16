"""End-to-end: HTTP POST /api/control -> server thread -> queued Qt signal ->
PlayerController.handle_remote_command runs on the MAIN thread.

Proves the threading bridge from app.py works (QMediaPlayer must only ever be
touched on the GUI thread).

Standalone:
    python tests/test_bridge_integration.py
"""
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from music_player.metadata_server import NowPlayingServer  # noqa: E402
from music_player.player_controller import PlayerController  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Bridge(QObject):
    command = Signal(str, dict)


def test_post_reaches_controller_on_main_thread():
    main_thread = threading.get_ident()
    controller = PlayerController()
    called = []
    handler_threads = []

    def fake_next():
        handler_threads.append(threading.get_ident())
        called.append("next")

    controller.next_track = fake_next

    bridge = _Bridge()
    bridge.command.connect(controller.handle_remote_command)
    srv = NowPlayingServer(
        controller.snapshot,
        command_handler=bridge.command.emit,
        playlist_provider=controller.playlist_payload,
        preferred_port=0,
    )
    srv.start()
    try:
        def do_post():
            req = urllib.request.Request(
                f"http://127.0.0.1:{srv.port}/api/control",
                data=json.dumps({"action": "next"}).encode(),
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3).read()

        t = threading.Thread(target=do_post)
        t.start()
        t.join()

        # The command is delivered as a queued event — pump the main-thread loop.
        deadline = time.time() + 2.0
        while not called and time.time() < deadline:
            _app.processEvents()
            time.sleep(0.01)

        assert called == ["next"], called
        assert handler_threads == [main_thread], (handler_threads, main_thread)
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
