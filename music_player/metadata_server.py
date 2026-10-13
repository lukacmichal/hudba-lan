from __future__ import annotations

import json
import queue
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from typing import TYPE_CHECKING, Callable

from music_player import __version__, __version_code__

if TYPE_CHECKING:
    from music_player.mys import DialkovaMys
    from music_player.streaming import FfmpegStreamManager

# Spojenie touchpadu, ktorym nic nepride, sa po tomto case zavrie. Telefon
# svoje necinne spojenie zavrie skor (60 s) a pri dalsom dotyku otvori nove —
# takze server nikdy nezavrie spojenie, do ktoreho telefon prave pise.
_MOUSE_IDLE_TIMEOUT_S = 180


_ALLOWED_ACTIONS = {
    "playpause", "stop", "next", "prev", "seek", "playIndex",
    "setVolume", "shutdown", "sleep", "sleep2", "spanok",
}


class NowPlayingServer:
    def __init__(
        self,
        payload_provider: Callable[[], dict],
        command_handler: "Callable[[str, dict], None] | None" = None,
        playlist_provider: "Callable[[], dict] | None" = None,
        stream_manager: "FfmpegStreamManager | None" = None,
        preferred_port: int = 8765,
        mouse: "DialkovaMys | None" = None,
    ) -> None:
        self._payload_provider = payload_provider
        self._command_handler = command_handler
        self._playlist_provider = playlist_provider
        self._stream_manager = stream_manager
        self._mouse = mouse
        self._preferred_port = preferred_port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.host = "0.0.0.0"
        self.local_ip = _local_ip_address()
        self.port = preferred_port

    @property
    def now_playing_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}/api/now-playing"

    @property
    def health_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}/health"

    @property
    def stream_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}/stream"

    def start(self) -> None:
        handler = self._handler_factory(
            self._payload_provider,
            self._stream_manager,
            self._command_handler,
            self._playlist_provider,
            self._mouse,
        )
        try:
            self._server = _LowLatencyHTTPServer((self.host, self._preferred_port), handler)
        except OSError:
            self._server = _LowLatencyHTTPServer((self.host, 0), handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._server:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

    @staticmethod
    def _handler_factory(
        payload_provider: Callable[[], dict],
        stream_manager: "FfmpegStreamManager | None",
        command_handler: "Callable[[str, dict], None] | None" = None,
        playlist_provider: "Callable[[], dict] | None" = None,
        mouse: "DialkovaMys | None" = None,
    ):
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
                )
                super().setup()

            def do_GET(self) -> None:
                if self.path == "/health":
                    # Verzia je tu preto, aby sa dala zistit ZVONKU. Prehravac
                    # sa presuva medzi dvoma notebookmi a otazka "ktoru verziu
                    # ma ten druhy" sa dovtedy nedala zodpovedat inak nez sadnut
                    # si k nemu — a preto sa ani nedalo povedat, ako velmi je
                    # pozadu. Odteraz staci:
                    #     curl http://<ip>:8765/health
                    self._send_json(
                        {
                            "status": "ok",
                            "version": __version__,
                            "versionCode": __version_code__,
                        },
                        HTTPStatus.OK,
                    )
                    return
                if self.path == "/api/now-playing":
                    try:
                        payload = payload_provider()
                    except Exception as exc:
                        self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                        return
                    self._send_json(payload, HTTPStatus.OK)
                    return
                if self.path == "/api/playlist":
                    if playlist_provider is None:
                        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                        return
                    try:
                        self._send_json(playlist_provider(), HTTPStatus.OK)
                    except Exception as exc:
                        self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                if self.path == "/stream":
                    Handler._handle_stream(self, stream_manager)
                    return
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                if self.path == "/api/mouse" and mouse is not None:
                    self._handle_mouse(mouse)
                    return
                if self.path != "/api/control" or command_handler is None:
                    self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0) or 0)
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    body = json.loads(raw or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError("body must be an object")
                    action = str(body.get("action", ""))
                except (ValueError, json.JSONDecodeError):
                    self._send_json({"error": "bad request"}, HTTPStatus.BAD_REQUEST)
                    return
                if action not in _ALLOWED_ACTIONS:
                    self._send_json({"error": "unknown action"}, HTTPStatus.BAD_REQUEST)
                    return
                params = {k: v for k, v in body.items() if k != "action"}
                try:
                    command_handler(action, params)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                self._send_json({"ok": True}, HTTPStatus.OK)

            def log_message(self, format: str, *args) -> None:
                return

            def _send_json(self, payload: dict, status: HTTPStatus) -> None:
                data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
                self.send_response(int(status))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle_mouse(self, mys: "DialkovaMys") -> None:
                """Trvale spojenie touchpadu: po hlavickach riadky az do EOF.

                Telo nema Content-Length — telefon pise, kym ma co. Odpoved
                (200 + "ok") ide hned, aby telefon vedel, ze PC touchpad pozna;
                starsia verzia by vratila 404.
                """
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"ok\n")
                self.wfile.flush()
                self.connection.settimeout(_MOUSE_IDLE_TIMEOUT_S)
                try:
                    while True:
                        riadok = self.rfile.readline(8192)
                        if not riadok:
                            break
                        mys.vykonaj(riadok.decode("utf-8", "replace").rstrip("\r\n"))
                except (OSError, ValueError):
                    pass
                finally:
                    mys.uvolni()

            @staticmethod
            def _handle_stream(
                handler: "Handler",
                mgr: "FfmpegStreamManager | None",
            ) -> None:
                if mgr is None or not mgr.status().active:
                    handler.send_response(503)
                    handler.send_header("Content-Type", "application/json")
                    handler.end_headers()
                    handler.wfile.write(b'{"error":"stream not active"}')
                    return

                q = mgr.subscribe()
                try:
                    content_type = getattr(mgr, "content_type", "application/octet-stream")
                    handler.send_response(200)
                    handler.send_header("Content-Type", content_type)
                    handler.send_header("Cache-Control", "no-cache, no-store")
                    handler.send_header("Connection", "close")
                    handler.end_headers()
                    while True:
                        try:
                            chunk = q.get(timeout=5)
                        except queue.Empty:
                            break  # ffmpeg stuck / timed out
                        if chunk is None:
                            break  # stream ended (new song or stop)
                        handler.wfile.write(chunk)
                        handler.wfile.flush()
                except Exception:
                    pass
                finally:
                    mgr.unsubscribe(q)

        return Handler


class _LowLatencyHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with TCP_NODELAY on the listening socket."""

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


def _local_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return str(sock.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
