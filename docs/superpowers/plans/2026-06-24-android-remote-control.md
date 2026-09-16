# Android diaľkové ovládanie + vypnutie PC — Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Projekt **nie je git repo** — kroky „Commit" sú nahradené kontrolnými bodmi (spustenie testov). Backend ide TDD cez `pytest`. Android sa testuje len obmedzene (JSON parsing); build/install rieši používateľ.

**Goal:** Rozšíriť Android appku o diaľkové ovládanie PC prehrávača (transport, seek, playlist, vypnutie PC) cez nové HTTP control endpointy.

**Architecture:** Telefón posiela `POST /api/control` → HTTP vlákno emituje Qt signal (queued) → hlavné vlákno volá `PlayerController`. Stav sa číta pollingom `/api/now-playing` (+ `playlistVersion`), playlist cez `/api/playlist` len pri zmene verzie.

**Tech Stack:** Python 3 / PySide6 / `http.server` (PC), Kotlin / Jetpack Compose / Coroutines (Android).

**Spec:** `docs/superpowers/specs/2026-06-24-android-remote-control-design.md`

---

## Chunk 1: PC Backend

### Task 1: `playlistVersion` + `playlist_payload()` v PlayerController

**Files:**
- Modify: `music_player/player_controller.py`
- Test: `tests/test_playlist_payload.py`

- [ ] **Step 1: Test** — `_playlist_version` bumpne pri zmene obsahu, nie pri `next_track`; `playlist_payload()` má správny tvar.

```python
# tests/test_playlist_payload.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from music_player.player_controller import PlayerController

@pytest.fixture
def ctrl(tmp_path):
    c = PlayerController()
    yield c

def _fake_tracks(monkeypatch, paths):
    from music_player import models
    monkeypatch.setattr(models, "collect_audio_paths", lambda p: list(paths))

def test_version_bumps_on_add(ctrl, monkeypatch):
    from music_player import player_controller as pc
    monkeypatch.setattr(pc, "collect_audio_paths", lambda p: ["a.mp3", "b.mp3"])
    v0 = ctrl.playlist_payload()["version"]
    ctrl.add_paths(["x"])
    assert ctrl.playlist_payload()["version"] > v0

def test_version_stable_on_navigation(ctrl, monkeypatch):
    from music_player import player_controller as pc
    monkeypatch.setattr(pc, "collect_audio_paths", lambda p: ["a.mp3", "b.mp3"])
    ctrl.add_paths(["x"])
    v = ctrl.playlist_payload()["version"]
    ctrl.current_index = 0
    ctrl.next_track()
    assert ctrl.playlist_payload()["version"] == v

def test_payload_shape(ctrl, monkeypatch):
    from music_player import player_controller as pc
    monkeypatch.setattr(pc, "collect_audio_paths", lambda p: ["a.mp3", "b.mp3"])
    ctrl.add_paths(["x"])
    p = ctrl.playlist_payload()
    assert set(p.keys()) == {"version", "currentIndex", "items"}
    assert p["items"][0].keys() >= {"index", "title", "artist", "durationMs"}
```

- [ ] **Step 2: Run, expect FAIL** — `pytest tests/test_playlist_payload.py -v` (no `playlist_payload`).

- [ ] **Step 3: Implement** in `player_controller.py`:
  - `__init__`: add `self._playlist_version = 0`.
  - Add helper:
    ```python
    def _bump_playlist_version(self) -> None:
        self._playlist_version += 1
    ```
  - Call `self._bump_playlist_version()` at the **start** of `add_paths` (when `added`), `move_indices` (when `sorted_src`), `remove_indices` (when `sorted_indices`), `clear_playlist`, and `load_state`.
  - Add method:
    ```python
    def playlist_payload(self) -> dict:
        return {
            "version": self._playlist_version,
            "currentIndex": self.current_index,
            "items": [
                {
                    "index": i,
                    "title": t.title,
                    "artist": t.artist,
                    "durationMs": int(getattr(t, "duration_ms", 0) or 0),
                }
                for i, t in enumerate(self.playlist)
            ],
        }
    ```
  - In `_refresh_snapshot`, add to payload: `"playlistVersion": self._playlist_version,`.

  > Pozn.: over reálne meno poľa pre dĺžku v `models.Track` (`duration_ms`?). Ak neexistuje, `getattr(..., 0)` vráti 0 — OK.

- [ ] **Step 4: Run, expect PASS** — `pytest tests/test_playlist_payload.py -v`.

### Task 2: `handle_remote_command()` v PlayerController

**Files:**
- Modify: `music_player/player_controller.py`
- Test: `tests/test_remote_command.py`

- [ ] **Step 1: Test** — každá akcia volá správnu metódu (spy).

```python
# tests/test_remote_command.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from music_player.player_controller import PlayerController

def test_dispatch(monkeypatch):
    c = PlayerController()
    calls = []
    for name in ("toggle_playback","stop","next_track","previous_track"):
        monkeypatch.setattr(c, name, lambda *a, n=name: calls.append(n))
    monkeypatch.setattr(c, "seek", lambda ms: calls.append(("seek", ms)))
    monkeypatch.setattr(c, "play_track_at", lambda i: calls.append(("idx", i)))
    c.handle_remote_command("playpause", {})
    c.handle_remote_command("stop", {})
    c.handle_remote_command("next", {})
    c.handle_remote_command("prev", {})
    c.handle_remote_command("seek", {"positionMs": 1234})
    c.handle_remote_command("playIndex", {"index": 3})
    assert calls == ["toggle_playback","stop","next_track","previous_track",("seek",1234),("idx",3)]

def test_unknown_action_noop(monkeypatch):
    c = PlayerController()
    c.handle_remote_command("bogus", {})  # nesmie hodiť výnimku

def test_shutdown(monkeypatch):
    c = PlayerController()
    import music_player.player_controller as pc
    fired = []
    monkeypatch.setattr(pc, "shutdown_windows", lambda: fired.append(True))
    c.handle_remote_command("shutdown", {})
    assert fired == [True]
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement:**
  ```python
  def handle_remote_command(self, action: str, params: dict) -> None:
      try:
          if action == "playpause":
              self.toggle_playback()
          elif action == "stop":
              self.stop()
          elif action == "next":
              self.next_track()
          elif action == "prev":
              self.previous_track()
          elif action == "seek":
              self.seek(int(params.get("positionMs", 0)))
          elif action == "playIndex":
              self.play_track_at(int(params.get("index", -1)))
          elif action == "shutdown":
              if not self._power_action_in_progress:
                  self._power_action_in_progress = True
                  shutdown_windows()
          # neznáme akcie ticho ignorujeme
      except (ValueError, TypeError, KeyError):
          pass
  ```

- [ ] **Step 4: Run, expect PASS.**

### Task 3: Control + playlist endpointy v `metadata_server.py`

**Files:**
- Modify: `music_player/metadata_server.py`
- Test: `tests/test_control_server.py`

- [ ] **Step 1: Test** — spustí `NowPlayingServer` s fake callbackmi na efemérnom porte, h1 `urllib` requesty.

```python
# tests/test_control_server.py
import json, urllib.request, urllib.error
from music_player.metadata_server import NowPlayingServer

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

def test_control_valid():
    srv, cmds = _make()
    try:
        url = f"http://127.0.0.1:{srv.port}/api/control"
        body = json.dumps({"action": "next"}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        assert cmds == [("next", {})]
    finally:
        srv.stop()

def test_control_unknown_action():
    srv, cmds = _make()
    try:
        url = f"http://127.0.0.1:{srv.port}/api/control"
        body = json.dumps({"action": "bogus"}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        try:
            urllib.request.urlopen(req)
            assert False, "expected 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        assert cmds == []
    finally:
        srv.stop()

def test_playlist_endpoint():
    srv, _ = _make()
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/api/playlist")
        data = json.loads(resp.read())
        assert data["version"] == 1
    finally:
        srv.stop()
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement:**
  - `__init__`: prijať `command_handler=None`, `playlist_provider=None`; uložiť.
  - Set povolených akcií: `_ALLOWED = {"playpause","stop","next","prev","seek","playIndex","shutdown"}` (modul-level).
  - `_handler_factory` rozšíriť o closure nad `command_handler`, `playlist_provider`.
  - V `Handler.do_GET` pridať vetvu `/api/playlist` → `playlist_provider()` (ak None → 404).
  - Pridať `do_POST`:
    ```python
    def do_POST(self) -> None:
        if self.path != "/api/control" or command_handler is None:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND); return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            action = str(body.get("action", ""))
        except (ValueError, json.JSONDecodeError):
            self._send_json({"error": "bad json"}, HTTPStatus.BAD_REQUEST); return
        if action not in _ALLOWED:
            self._send_json({"error": "unknown action"}, HTTPStatus.BAD_REQUEST); return
        params = {k: v for k, v in body.items() if k != "action"}
        command_handler(action, params)
        self._send_json({"ok": True}, HTTPStatus.OK)
    ```

- [ ] **Step 4: Run, expect PASS** — `pytest tests/ -v`.

### Task 4: Qt bridge v `app.py`

**Files:**
- Modify: `music_player/app.py`

- [ ] **Step 1: Implement** (integration, manuálna verifikácia):
  ```python
  from PySide6.QtCore import QObject, Signal

  class RemoteCommandBridge(QObject):
      command = Signal(str, dict)
  ```
  Pri vytváraní servera (~`app.py:72`):
  ```python
  bridge = RemoteCommandBridge()
  bridge.command.connect(controller.handle_remote_command)
  api_server = NowPlayingServer(
      controller.snapshot,
      command_handler=bridge.command.emit,
      playlist_provider=controller.playlist_payload,
      stream_manager=stream_manager,
  )
  ```
  Drž `bridge` referenciu nažive (napr. atribút na window/app), aby ho GC nezhodil.

- [ ] **Step 2: Manuálna verifikácia** — spusti appku, `curl -X POST http://<ip>:8765/api/control -d '{"action":"next"}'` → preskočí skladbu; `curl http://<ip>:8765/api/playlist` → JSON.

---

## Chunk 2: Android klient

> Build/install rieši používateľ. Cesty: `android/app/src/main/java/sk/lanmusic/`.

### Task 5: Model + poller rozšírenie

**Files:**
- Modify: `metadata/NowPlayingState.kt`, `metadata/MetadataPoller.kt`

- [ ] Rozšíriť `NowPlayingState` o `positionMs: Long = 0`, `durationMs: Long = 0`, `currentIndex: Int = -1`, `playlistVersion: Int = 0`.
- [ ] V `MetadataPoller.fetchNowPlaying` doplniť: `positionMs = json.optLong("positionMs")`, `durationMs = json.optLong("durationMs")`, `currentIndex = json.optInt("currentIndex", -1)`, `playlistVersion = json.optInt("playlistVersion", 0)`.

### Task 6: `RemoteControlClient.kt` (nový)

**Files:**
- Create: `control/RemoteControlClient.kt`

- [ ] Implement:
  ```kotlin
  package sk.lanmusic.control
  import kotlinx.coroutines.Dispatchers
  import kotlinx.coroutines.withContext
  import org.json.JSONObject
  import java.net.HttpURLConnection
  import java.net.URL

  class RemoteControlClient(private val ip: String, private val port: Int) {
      private suspend fun post(body: JSONObject) = withContext(Dispatchers.IO) {
          runCatching {
              val c = URL("http://$ip:$port/api/control").openConnection() as HttpURLConnection
              c.requestMethod = "POST"; c.doOutput = true
              c.connectTimeout = 2000; c.readTimeout = 2000
              c.setRequestProperty("Content-Type", "application/json")
              c.outputStream.use { it.write(body.toString().toByteArray()) }
              c.responseCode; c.disconnect()
          }
      }
      suspend fun playPause() = post(JSONObject().put("action", "playpause"))
      suspend fun stop()      = post(JSONObject().put("action", "stop"))
      suspend fun next()      = post(JSONObject().put("action", "next"))
      suspend fun prev()      = post(JSONObject().put("action", "prev"))
      suspend fun seek(ms: Long) = post(JSONObject().put("action", "seek").put("positionMs", ms))
      suspend fun playIndex(i: Int) = post(JSONObject().put("action", "playIndex").put("index", i))
      suspend fun shutdown()  = post(JSONObject().put("action", "shutdown"))
  }
  ```

### Task 7: `PlaylistRepository.kt` (nový)

**Files:**
- Create: `playlist/PlaylistRepository.kt`

- [ ] `data class PlaylistItem(val index: Int, val title: String, val artist: String, val durationMs: Long)`.
- [ ] `suspend fun fetch(ip, port): List<PlaylistItem>?` — GET `/api/playlist`, parse `items[]`. ViewModel volá len keď `playlistVersion` sa zmenil.

### Task 8: `PlayerScreen.kt` redizajn

**Files:**
- Modify: `ui/PlayerScreen.kt`

- [ ] Horná lišta: `StatusChip` vľavo + `IconButton` (power) vpravo. Power → `showShutdownDialog = true`.
- [ ] `if (showShutdownDialog) AlertDialog(...)` — text „Naozaj vypnúť PC?", confirm „Áno" (červené) → `onShutdown()`, dismiss „Zrušiť".
- [ ] Now-playing: title + artist (zachovať).
- [ ] `Slider` (seek): hodnota = `if (dragging) localPos else positionMs`; `onValueChange` → `dragging=true; localPos=it`; `onValueChangeFinished` → `dragging=false; onSeek(localPos)`. Časy `mm:ss` z `positionMs`/`durationMs`.
- [ ] Transport `Row`: `IconButton` prev/playpause/next/stop (`Icons.Filled.SkipPrevious`, `PlayArrow`/`Pause`, `SkipNext`, `Stop`). Ikona play/pause podľa `uiState.nowPlaying.state == "playing"`.
- [ ] `LazyColumn` playlist: každá položka klikateľná → `onPlayIndex(item.index)`; aktuálna (`index == currentIndex`) zvýraznená (napr. `primaryContainer` pozadie).
- [ ] Aktualizovať signatúru `PlayerScreen(...)` o nové lambdy: `onPrev`, `onPlayPause`, `onNext`, `onStop`, `onSeek`, `onPlayIndex`, `onShutdown`, `playlist`.

### Task 9: `PlayerViewModel.kt` wiring

**Files:**
- Modify: `ui/PlayerViewModel.kt`

- [ ] V `PlayerUiState` pridať `playlist: List<PlaylistItem> = emptyList()`.
- [ ] Pri `DiscoveryState.Found` vytvoriť `RemoteControlClient(ip, port)` a uložiť; v `startMetadataPoller` sledovať `playlistVersion` a pri zmene zavolať `PlaylistRepository.fetch` → update `playlist`.
- [ ] Metódy `onPrev/onPlayPause/onNext/onStop/onSeek/onPlayIndex/onShutdown` → `viewModelScope.launch { controlClient?.xxx() }`. Pri `onPlayPause` optimisticky preklopiť `state` v `_uiState`.
- [ ] `MainActivity` napojiť nové lambdy do `PlayerScreen`.

- [ ] **Verifikácia (používateľ):** build & install APK, otestovať na telefóne proti bežiacemu PC: transport, seek, ťuknutie na skladbu, vypnutie PC cez dialóg.

---

## Mimo rozsahu
Hlasitosť, úprava playlistu z telefónu, sleep, auth, WebSocket.
