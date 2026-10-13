from __future__ import annotations

import ctypes
import os
import sys

os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

# Unique AppUserModelID — tells Windows this is a standalone app,
# not just another pythonw.exe process.  Gives it its own taskbar
# icon and prevents icon sharing with other Python scripts.
from music_player.system_integration import APP_USER_MODEL_ID, register_app_identity

ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
try:
    # Friendly name + icon for toast notifications (instead of the raw ID).
    register_app_identity()
except OSError:
    pass

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from music_player.metadata_server import NowPlayingServer
from music_player.mys import DialkovaMys
from music_player.beacon import UdpBeaconSender
from music_player.persistence import StateStore
from music_player.player_controller import PlayerController
from music_player.streaming import FfmpegStreamManager
from music_player.system_integration import is_autostart_enabled
from music_player.media_keys import MediaKeyListener
from music_player.ui import MainWindow


_SINGLE_INSTANCE_KEY = "Codex.MetalMusicPlayer.SingleInstance.v1"


class RemoteCommandBridge(QObject):
    """Marshals remote-control commands from the HTTP server thread onto the
    Qt main thread. ``command.emit`` is thread-safe; because the receiver lives
    on the main thread the call is queued there, so QMediaPlayer is only ever
    touched from the GUI thread."""

    command = Signal(str, dict)


def _try_signal_existing_instance() -> bool:
    """Return True if another instance is already running and was signalled."""
    probe = QLocalSocket()
    probe.connectToServer(_SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(500):
        probe.write(b"show\n")
        probe.flush()
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return True
    return False


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Metal Music Player")
    app.setOrganizationName("Codex")

    # Single-instance guard: if another instance is already running, ping it
    # to surface its window and exit quietly instead of starting a duplicate.
    if _try_signal_existing_instance():
        return

    # We are the first instance — set up a local server so future invocations
    # can signal us to un-minimize/raise instead of spawning duplicates.
    # Remove any stale server file left over from a previous crash.
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    single_instance_server = QLocalServer()
    single_instance_server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    single_instance_server.listen(_SINGLE_INSTANCE_KEY)

    state_store = StateStore()
    state = state_store.load()

    controller = PlayerController()
    from music_player.statistika import Statistika, predvolena_cesta
    controller.statistika = Statistika(predvolena_cesta())
    stream_manager = FfmpegStreamManager()
    controller.attach_stream_manager(stream_manager)
    controller.load_state(state)

    command_bridge = RemoteCommandBridge()
    command_bridge.command.connect(controller.handle_remote_command)
    api_server = NowPlayingServer(
        controller.snapshot,
        command_handler=command_bridge.command.emit,
        playlist_provider=controller.playlist_payload,
        stream_manager=stream_manager,
        mouse=DialkovaMys(),
    )
    api_server.start()
    stream_manager.set_http_stream_url(api_server.stream_url)
    controller.set_api_url(api_server.now_playing_url)

    beacon = UdpBeaconSender(api_port=api_server.port)
    beacon.start()

    window = MainWindow(
        controller,
        state_store,
        api_url=api_server.now_playing_url,
        autostart_enabled=state.start_with_windows or is_autostart_enabled(),
        playlist_visible=state.playlist_window_visible,
        window_width=state.window_width,
        full_height=state.playlist_window_height,
    )
    # Dark title bar on Windows 10/11
    try:
        import ctypes
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        hwnd = int(window.winId())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int),
        )
    except Exception:
        pass
    from music_player.config_loader import get_deepl_api_key
    window.lyrics_edit.set_api_key(get_deepl_api_key())

    window.show()
    controller.start_scheduled_timer()

    def _raise_window() -> None:
        # Undo tray-minimize and bring the window to the foreground.
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def _on_new_instance_connection() -> None:
        socket = single_instance_server.nextPendingConnection()
        if socket is None:
            return

        def _read_and_close() -> None:
            # Drain whatever the probe sent (we only care that someone pinged).
            try:
                socket.readAll()
            except Exception:
                pass
            _raise_window()
            socket.disconnectFromServer()
            socket.deleteLater()

        socket.readyRead.connect(_read_and_close)
        # If the probe disconnects before readyRead fires, still honor the ping.
        socket.disconnected.connect(_read_and_close)

    single_instance_server.newConnection.connect(_on_new_instance_connection)

    media_keys = MediaKeyListener()
    media_keys.play_pause_pressed.connect(controller.toggle_playback)
    media_keys.start()

    autosave_timer = QTimer()
    autosave_timer.setInterval(3000)
    autosave_timer.timeout.connect(window.save_state)
    autosave_timer.start()

    runtime_refresh_timer = QTimer()
    runtime_refresh_timer.setInterval(1000)
    runtime_refresh_timer.timeout.connect(controller.refresh_runtime_state)
    runtime_refresh_timer.start()

    def _cleanup() -> None:
        window.save_state()
        stream_manager.stop()
        api_server.stop()
        beacon.stop()
        try:
            single_instance_server.close()
        except Exception:
            pass
        QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)

    app.aboutToQuit.connect(_cleanup)
    sys.exit(app.exec())
