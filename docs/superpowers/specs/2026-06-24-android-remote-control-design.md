# Android diaľkové ovládanie + vypnutie PC — Design Spec

**Dátum:** 2026-06-24
**Stav:** Schválené

## Prehľad

Rozšírenie existujúcej Android appky (dnes len prijímač streamu) o **diaľkové ovládanie PC prehrávača**:

- Transport: predchádzajúca / play-pauza / nasledujúca / stop
- Seek bar s časom (pretáčanie)
- Zobrazenie **celého playlistu** + ťuknutím na skladbu ju prehrať
- Tlačidlo na **okamžité vypnutie PC** s potvrdzovacím dialógom (poistka proti omylu)

Telefón ostáva zároveň prijímačom streamu. Transport ovláda **PC (zdroj)**, telefón zrkadlí stav a auto-prijíma stream ako doteraz.

Vyžaduje nové control endpointy na PC HTTP serveri (`metadata_server.py`) + bridge z HTTP vlákna na Qt hlavné vlákno.

## Architektúra / Data flow

```
Telefón ──POST /api/control {action}──▶ HTTP vlákno ──Qt signal (queued)──▶ hlavné vlákno ──▶ PlayerController
Telefón ──GET /api/now-playing (2s)──▶ stav + playlistVersion
Telefón ──GET /api/playlist (len keď sa playlistVersion zmení)──▶ položky playlistu
```

- Príkazy sú fire-and-forget. Klient nečaká na výsledok akcie — nový stav zistí z najbližšieho pollingu now-playing (optimistic UI medzitým).
- `playlistVersion` sa mení **len pri zmene obsahu playlistu** (pridanie/odobratie/presun/vyčistenie), nie pri zmene `currentIndex`. Aktuálnu skladbu klient zvýrazňuje cez `currentIndex` z now-playing bez refetchu.

## PC Backend

### `metadata_server.py`

`NowPlayingServer` dostane dva nové callbacky popri existujúcom `payload_provider`:

```python
command_handler: Callable[[str, dict], None]   # thread-safe, emituje Qt signal
playlist_provider: Callable[[], dict]          # vráti payload playlistu
```

- **`do_POST`** → route `/api/control`:
  - Prečíta `Content-Length`, naparsuje JSON `{action, ...params}`.
  - Ak `action` nie je v povolenej množine → `400 {"error": "unknown action"}`.
  - Inak zavolá `command_handler(action, params)` a vráti `200 {"ok": true}`.
  - Povolené akcie: `playpause`, `stop`, `next`, `prev`, `seek`, `playIndex`, `shutdown`.
- **`do_GET` → `/api/playlist`**: vráti `playlist_provider()`:
  ```json
  {"version": 7, "currentIndex": 2,
   "items": [{"index": 0, "title": "...", "artist": "...", "durationMs": 213000}, ...]}
  ```
- Ostatné GET endpointy (`/health`, `/api/now-playing`, `/stream`) bez zmeny.

### Qt bridge — `app.py`

HTTP server beží na vlákne, ale `QMediaPlayer`/`QAudioOutput` sa smú volať **len z hlavného Qt vlákna**. Premostenie cez Qt signal s queued connection:

```python
class RemoteCommandBridge(QObject):
    command = Signal(str, dict)

bridge = RemoteCommandBridge()
bridge.command.connect(controller.handle_remote_command)  # auto → queued (cross-thread)
api_server = NowPlayingServer(
    controller.snapshot,
    command_handler=bridge.command.emit,      # volané z HTTP vlákna, thread-safe
    playlist_provider=controller.playlist_payload,
    stream_manager=stream_manager,
)
```

`bridge.command.emit(...)` z HTTP vlákna sa vďaka rozdielnej thread affinity príjemcu zaradí do fronty hlavného vlákna — žiadne race conditions, idiomatické Qt.

### `player_controller.py`

**`handle_remote_command(action, params)`** — slot bežiaci na hlavnom vlákne, dispatch na existujúce metódy:

| action | volá |
|---|---|
| `playpause` | `toggle_playback()` |
| `stop` | `stop()` |
| `next` | `next_track()` |
| `prev` | `previous_track()` |
| `seek` | `seek(int(params["positionMs"]))` |
| `playIndex` | `play_track_at(int(params["index"]))` |
| `shutdown` | `shutdown_windows()` (chránené `_power_action_in_progress`) |

Neznáme/chybné parametre sa ticho ignorujú (existujúce metódy si index/pozíciu samy validujú a klampujú).

**`playlist_payload()`** → `{"version": <int>, "currentIndex": <int>, "items": [...]}`. Položky z `self.playlist`, `durationMs` z `Track` ak je dostupné (inak 0).

**`playlistVersion`**:
- Nové pole `self._playlist_version: int = 0`, helper `_bump_playlist_version()` zvýši o 1.
- Volá sa **len** pri zmene obsahu: `add_paths`, `move_indices`, `remove_indices`, `clear_playlist`, `load_state`.
- Pridá sa do snapshotu (`_refresh_snapshot`) ako `"playlistVersion"`.

**Snapshot** (`_refresh_snapshot`): pridať `"playlistVersion"`. `positionMs`, `durationMs`, `currentIndex`, `state` tam už sú.

### `system_integration.py`

Bez zmeny — reuse `shutdown_windows()` (`shutdown /s /t 0`).

## Android

### `metadata/NowPlayingState.kt` + `MetadataPoller.kt`

Pridať polia do modelu a parsovania: `positionMs: Long`, `durationMs: Long`, `currentIndex: Int`, `playlistVersion: Int`. `state` už je.

### `control/RemoteControlClient.kt` (nový)

```kotlin
suspend fun sendCommand(action: String, params: JSONObject = JSONObject())
```
POST JSON na `http://$ip:$port/api/control` (Dispatchers.IO, krátky timeout, fire-and-forget). Pohodlné wrappery: `playPause()`, `stop()`, `next()`, `prev()`, `seek(ms)`, `playIndex(i)`, `shutdown()`.

### `playlist/PlaylistRepository.kt` (nový)

Drží `List<PlaylistItem>` + `lastVersion`. Keď `nowPlaying.playlistVersion != lastVersion` → GET `/api/playlist`, aktualizuje zoznam. `PlaylistItem(index, title, artist, durationMs)`.

### `ui/PlayerScreen.kt` (redizajn)

- **Horná lišta:** status chip (vľavo) + **power ikona (vpravo)**, oddelená od transportu. Ťuknutie → `AlertDialog` „Naozaj vypnúť PC?" → **Áno** (červené) / **Zrušiť**. Potvrdenie → `control.shutdown()`.
- **Now-playing:** title + artist.
- **Seek bar:** `Slider` s pozíciou; počas ťahania sa drží lokálna hodnota a ignoruje sa prichádzajúci `positionMs` (nebije sa s používateľom), po pustení → `control.seek(ms)`. Vedľa uplynulý/celkový čas `mm:ss`.
- **Transport riadok:** ⏮ `prev` · ⏯ `playpause` (ikona podľa `state`) · ⏭ `next` · ⏹ `stop`.
- **Playlist:** `LazyColumn` položiek; aktuálna (`currentIndex`) zvýraznená; ťuknutie → `control.playIndex(index)`.

### `ui/PlayerViewModel.kt`

- Tlačidlá → `RemoteControlClient`.
- **Optimistic UI:** pri play/pauze hneď preklopí lokálny `state`, zosúladí sa najbližším pollingom.
- Spravuje `PlaylistRepository`, vystavuje rozšírený `PlayerUiState` (now-playing + playlist).
- Príjem streamu ostáva ako je (auto-pripojenie keď `streamingActive`). Pri pauze/seek krátky výpadok streamu je akceptovaný; po obnovení sa telefón auto-pripojí.

## Bezpečnosť

Control API je **bez autentifikácie**, vrátane `shutdown` — konzistentné so zvyškom systému (LAN only). Vedomé rozhodnutie pre domácu sieť. Voliteľný token sa dá doplniť neskôr.

## Dotknuté súbory

| Súbor | Zmena |
|---|---|
| `music_player/metadata_server.py` | `do_POST` + `/api/control`, `GET /api/playlist`, 2 nové callbacky |
| `music_player/player_controller.py` | `handle_remote_command`, `playlist_payload`, `_playlist_version` + bump, snapshot `+playlistVersion` |
| `music_player/app.py` | `RemoteCommandBridge`, prepojenie signálu, podanie callbackov serveru |
| `music_player/system_integration.py` | bez zmeny (reuse `shutdown_windows`) |
| `android/.../metadata/NowPlayingState.kt` | +polia |
| `android/.../metadata/MetadataPoller.kt` | parse +polia |
| `android/.../control/RemoteControlClient.kt` | **nový** |
| `android/.../playlist/PlaylistRepository.kt` | **nový** |
| `android/.../ui/PlayerScreen.kt` | redizajn (transport, seek, playlist, power) |
| `android/.../ui/PlayerViewModel.kt` | wiring control + playlist |

## Testy (pytest, `tests/`)

- `handle_remote_command` — každá akcia volá správnu metódu (fake/monkeypatch controller alebo špión na metódach).
- `playlist_payload` — tvar payloadu, indexy, `currentIndex`.
- `_playlist_version` — bumpne pri `add_paths`/`remove_indices`/`move_indices`/`clear_playlist`, **nebumpne** pri zmene `current_index` (napr. `next_track`).
- `POST /api/control` — neznáma akcia → 400; validná → `command_handler` zavolaný so správnymi argumentmi.
- `GET /api/playlist` — vráti payload z provideru.

## Mimo rozsahu

- Hlasitosť, úprava playlistu z telefónu (mazanie/poradie), uspanie (sleep), autentifikácia, WebSocket push.
