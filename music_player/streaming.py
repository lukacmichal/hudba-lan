from __future__ import annotations

import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class StreamStatus:
    available: bool
    active: bool
    url: str
    target: str
    codec: str
    last_error: str = ""


class FfmpegStreamManager:
    def __init__(self) -> None:
        self.ffmpeg_path = _detect_ffmpeg_path()
        self.ffprobe_path = _detect_ffprobe_path()
        self.max_bitrate_kbps = 160
        self.sample_rate = 48000
        self.channels = 2
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._current_path = ""
        self._current_position_ms = 0
        self._last_error = ""
        self._http_stream_url: str = ""

        # Codec selection: prefer Opus (lower latency) with AAC-LC fallback
        self._use_opus = self._has_opus_encoder()
        self.codec = "Opus" if self._use_opus else "AAC-LC"
        self.content_type = "video/MP2T"

        # Subscriber queues — each HTTP client gets its own queue
        # Smaller queue (was 512) — on LAN, data flows fast; large queue = stale data
        self._subscribers: list[queue.Queue] = []
        self._subs_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None

    def set_http_stream_url(self, url: str) -> None:
        self._http_stream_url = url

    @property
    def client_url(self) -> str:
        return self._http_stream_url

    @property
    def available(self) -> bool:
        return self.ffmpeg_path is not None

    def status(self) -> StreamStatus:
        with self._lock:
            active = self._process is not None and self._process.poll() is None
            return StreamStatus(
                available=self.available,
                active=active,
                url=self.client_url,
                target="pipe:1",
                codec=self.codec,
                last_error=self._last_error,
            )

    def subscribe(self) -> queue.Queue:
        """Register an HTTP client. Returns a Queue; None value = stream ended."""
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._subs_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._subs_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def start_track(self, track_path: str, position_ms: int = 0) -> bool:
        if not self.available or self.ffmpeg_path is None:
            self._remember_error("ffmpeg nebol najdeny.")
            return False

        resolved_path = str(Path(track_path).expanduser().resolve())
        safe_position_ms = max(int(position_ms), 0)

        with self._lock:
            restart_needed = True
            if self._process is not None and self._process.poll() is None:
                restart_needed = not (
                    self._current_path.lower() == resolved_path.lower()
                    and abs(self._current_position_ms - safe_position_ms) < 350
                )
            if not restart_needed:
                return True
            self._stop_locked()

            command = self._build_command(resolved_path, safe_position_ms)
            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as exc:
                self._process = None
                self._remember_error(f"ffmpeg sa nepodarilo spustit: {exc}")
                return False

            self._current_path = resolved_path
            self._current_position_ms = safe_position_ms
            self._last_error = ""
            self._start_reader_thread(self._process)
            return True

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._current_path = ""
        self._current_position_ms = 0
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.5)

    def _start_reader_thread(self, process: subprocess.Popen) -> None:
        t = threading.Thread(
            target=self._read_loop, args=(process,), daemon=True, name="ffmpeg-reader"
        )
        t.start()
        self._reader_thread = t

    def _read_loop(self, process: subprocess.Popen) -> None:
        stdout = process.stdout
        if stdout is None:
            return
        try:
            while True:
                data = stdout.read(1024)
                if not data:
                    break
                self._broadcast(data)
        finally:
            self._broadcast_eof()

    def _broadcast(self, data: bytes) -> None:
        with self._subs_lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(data)
                except queue.Full:
                    pass  # slow client — drop chunk

    def _broadcast_eof(self) -> None:
        with self._subs_lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass

    def _effective_bitrate(self, track_path: str) -> str:
        bitrate_kbps = self.max_bitrate_kbps
        if self.ffprobe_path is not None:
            source_kbps = _probe_audio_bitrate(self.ffprobe_path, track_path)
            if source_kbps is not None and source_kbps < bitrate_kbps:
                bitrate_kbps = source_kbps
        return f"{bitrate_kbps}k"

    def _has_opus_encoder(self) -> bool:
        """Check whether the local FFmpeg build includes libopus."""
        if self.ffmpeg_path is None:
            return False
        try:
            result = subprocess.run(
                [str(self.ffmpeg_path), "-encoders"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return "libopus" in result.stdout
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _build_command(self, track_path: str, position_ms: int) -> list[str]:
        assert self.ffmpeg_path is not None
        bitrate = self._effective_bitrate(track_path)
        command = [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            # Faster stream start — skip long input analysis
            "-probesize",
            "32768",
            "-analyzeduration",
            "0",
        ]
        if position_ms > 0:
            command.extend(["-ss", f"{position_ms / 1000.0:.3f}"])
        command.extend(
            [
                "-re",
                "-i",
                track_path,
                "-vn",
                "-map",
                "0:a:0",
                "-ac",
                str(self.channels),
                "-ar",
                str(self.sample_rate),
            ]
        )
        if self._use_opus:
            # Opus — lower algorithmic delay than AAC (~10ms vs ~21ms)
            command.extend(
                [
                    "-c:a",
                    "libopus",
                    "-b:a",
                    bitrate,
                    "-application",
                    "audio",
                    "-frame_duration",
                    "10",
                ]
            )
        else:
            command.extend(
                [
                    "-c:a",
                    "aac",
                    "-b:a",
                    bitrate,
                ]
            )
        # MPEGTS container — proven compatibility with LibVLC
        command.extend(
            [
                "-fflags",
                "+nobuffer",
                "-flags",
                "+low_delay",
                "-flush_packets",
                "1",
                "-muxdelay",
                "0",
                "-muxpreload",
                "0",
                "-f",
                "mpegts",
                "pipe:1",
            ]
        )
        return command

    def _remember_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message


def _probe_audio_bitrate(ffprobe_path: Path, track_path: str) -> int | None:
    """Return audio bitrate in kbps, or None if probing fails."""
    try:
        result = subprocess.run(
            [
                str(ffprobe_path),
                "-v", "quiet",
                "-select_streams", "a:0",
                "-show_entries", "stream=bit_rate",
                "-of", "csv=p=0",
                track_path,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = result.stdout.strip()
        if raw and raw.isdigit():
            return int(raw) // 1000
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _detect_ffmpeg_path() -> Path | None:
    discovered = shutil.which("ffmpeg")
    if discovered:
        return Path(discovered).resolve()

    candidates = [
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _detect_ffprobe_path() -> Path | None:
    discovered = shutil.which("ffprobe")
    if discovered:
        return Path(discovered).resolve()
    ffmpeg = _detect_ffmpeg_path()
    if ffmpeg:
        ffprobe = ffmpeg.parent / "ffprobe.exe"
        if ffprobe.exists():
            return ffprobe.resolve()
    return None
