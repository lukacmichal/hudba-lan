# Android LAN Music Client — Design Spec

**Dátum:** 2026-03-14
**Projekt:** LAN Music Player
**Rozsah:** Android klient + UDP beacon na serveri

---

## Cieľ

Jednoduchá Android appka ktorá sa po spustení automaticky pripojí na existujúci UDP multicast audio stream zo servera (Windows PC), zobrazí názov aktuálnej skladby a interpreta, a hrá nepretržite aj keď je minimalizovaná alebo telefón zamknutý. Používateľ nemusí nič nastavovať.

---

## Čo sa nemení

- Windows Python app (PySide6) zostáva bez zmeny v logike prehrávania a streamovania
- Stream: UDP multicast `udp://@239.255.12.42:5004`, kontajner MPEG-TS, kodek AAC-LC 160kbps 48kHz stereo
- Metadata API: `GET http://<ip>:8765/api/now-playing` (existujúci `NowPlayingServer`)

---

## Čo sa pridá na serveri

### `music_player/beacon.py` — `UdpBeaconSender`

Nová trieda, nezávislá od zvyšku. Každé 2 sekundy broadcastuje UDP packet na port `8766` (LAN broadcast `255.255.255.255`):

```json
{"service": "lan-music-player", "ip": "192.168.x.x", "apiPort": 8765}
```

- IP sa zisťuje rovnako ako v `metadata_server.py` (`_local_ip_address()`)
- Beží vo vlastnom daemon threade
- `start()` / `stop()` rozhranie

### `app.pyw` zmeny

- Vytvorí `UdpBeaconSender`, zavolá `.start()` pri štarte appky
- Zavolá `.stop()` pri zaváraní appky

---

## Android app

### Tech stack

- Kotlin
- Jetpack Compose (UI)
- LibVLC Android (`org.videolan.android:libvlc-all`)
- Kotlin Coroutines + StateFlow
- OkHttp (HTTP metadata polling)
- Foreground Service (audio playback na pozadí)

### Minimálna verzia Androidu

API 21 (Android 5.0) — požiadavka LibVLC.

---

## Komponenty

### 1. `UdpDiscoveryManager`

**Zodpovednosť:** Nájsť IP adresu servera.

**Postup:**
1. Načítaj cached IP z `SharedPreferences`
2. Ak existuje: pošli `GET /health` — ak odpovie `200 OK` → použij ju, koniec
3. Ak nie: otvor `DatagramSocket` s `setReuseAddress(true)` pred `bind()`, viazaný na `0.0.0.0:8766`, nastav `setBroadcast(true)`, čakaj na beacon packet (timeout 10s). Server broadcastuje na `255.255.255.255` (limited broadcast) — `SO_REUSEADDR` je potrebný pre spoľahlivé prijímanie na niektorých Android kerneloch.
4. Parsuj JSON — **najprv over `service == "lan-music-player"`**, inak packet zahoď a čakaj ďalej; pri parse chybe taktiež zahoď
5. Extrahuj `ip` + `apiPort`, ulož do `SharedPreferences`
6. Ak timeout (10s) uplynie bez validného packetu → stav `ServerNotFound`, opakuj každých 5s

**Stav:** `Discovering` → `Found(ip, port)` → `NotFound`

---

### 2. `StreamService` (Android Foreground Service)

**Zodpovednosť:** Nepretržité prehrávanie UDP multicast streamu.

**Správanie:**
- Spustí sa pri otvorení `MainActivity`
- Vytvorí LibVLC inštanciu s parametrami:
  ```
  --network-caching=150
  --no-video
  --aout=opensles
  ```
- Hrá: `udp://@239.255.12.42:5004?fifo_size=1000000&overrun_nonfatal=1`
- Vystaví `StateFlow<PlaybackState>` (Playing / Stopped / Error)
- Foreground notifikácia: názov skladby (aktualizuje sa) + Stop tlačidlo
- `stop()` → zastaví LibVLC, zruší notifikáciu, service ostane alive (pre prípadné reštartovanie)
- `play()` → znova naštartuje LibVLC s rovnakou URL
- Pri `onDestroy` → LibVLC uvoľní zdroje

**Prečo foreground service:** Android zastaví background procesy, foreground service s notifikáciou je povinná pre audio appky.

---

### 3. `MetadataPoller`

**Zodpovednosť:** Získavanie informácií o aktuálnej skladbe.

**Postup:**
- Spustí sa keď `UdpDiscoveryManager` nájde server IP
- Coroutine loop: každé 2s `GET http://<ip>:<port>/api/now-playing`
- Parsuje: `title`, `artist`, `state`, `streamingActive`
- Emituje `StateFlow<NowPlayingState>`
- Ak 3 requesty za sebou zlyhajú (timeout / connection refused) → emituje `ServerLost`
- Pri `ServerLost`: coroutine sa zruší (`cancel()`), `UdpDiscoveryManager` sa reštartuje (vymaže cached IP, spustí beacon listening)
- Keď discovery nájde IP (rovnakú alebo novú) → `MetadataPoller` sa vytvorí nanovo a spustí

---

### 4. `MainActivity` (Jetpack Compose)

**Jedna obrazovka:**

```
┌─────────────────────────────┐
│  ● Pripojene                │  ← farebný chip: Hladam... / Pripojene / Nedostupny
│                             │
│                             │
│      Midnight City          │  ← title, veľké písmo, zalamuje
│      M83                    │  ← artist, menšie
│                             │
│                             │
│         [ ■ Stop ]          │  ← ak hrá; [ ▶ Prehrať ] ak stopped
│                             │
│   udp://239.255.12.42:5004  │  ← malý text, šedý
└─────────────────────────────┘
```

**Stavy UI:**
| Stav | Indikátor | Tlačidlo |
|------|-----------|----------|
| Hľadám server | žltý, animovaný | — |
| Pripájam stream | modrý, animovaný | — |
| Hrá | zelený | Stop |
| Zastavené | šedý | Prehrať |
| Server nedostupný | červený | Reconnect |

**Životný cyklus:**
- `onStart` → zavolaj `startForegroundService(StreamService)`, potom `bindService(StreamService)`, spusti `UdpDiscoveryManager`
- `onStop` → unbind (service pokračuje, lebo bol spustený cez `startForegroundService` — nezomrie po unbind)

---

## Dátový tok

```
App štart
  │
  ├─► StreamService.play()          (audio okamžite, bez čakania na IP)
  │     LibVLC → udp://239.255.12.42:5004
  │
  └─► UdpDiscoveryManager.start()
        │
        ├─ cached IP OK? ──► MetadataPoller.start(ip)
        │                         │
        │                         └─► každé 2s GET /api/now-playing
        │                                   └─► UI: title, artist
        │
        └─ nie ──► čakaj na UDP beacon (port 8766)
                       └─ nájdené ──► ulož IP ──► MetadataPoller.start(ip)
```

---

## Štruktúra projektu (Android)

```
app/
  src/main/
    java/sk/lanmusic/
      MainActivity.kt
      ui/
        PlayerScreen.kt         ← Compose UI
        PlayerViewModel.kt      ← StateFlow, koordinuje service + poller
      service/
        StreamService.kt        ← foreground service, LibVLC
      discovery/
        UdpDiscoveryManager.kt
      metadata/
        MetadataPoller.kt
        NowPlayingState.kt      ← data class
    AndroidManifest.xml
  build.gradle.kts
```

---

## Oprávnenia (AndroidManifest)

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK" />
<uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE" />

<!-- StreamService musí mať foregroundServiceType, inak crash na API 29+ -->
<service
    android:name=".service.StreamService"
    android:foregroundServiceType="mediaPlayback" />
```

> `CHANGE_WIFI_MULTICAST_STATE` samotné nestačí. `StreamService` musí pri štarte získať `WifiManager.MulticastLock` volaním `wifiManager.createMulticastLock("lan-music").apply { setReferenceCounted(false); acquire() }` a uvolniť ho pri `onDestroy`. Bez toho Wi-Fi čip multicast pakety zahodí aj s oprávnením.

---

## MediaSession (Android 13+)

`StreamService` musí vytvoriť a udržiavať `MediaSessionCompat` (alebo `MediaSession` pre API 33+). Bez aktívnej `MediaSession` Android 13+ negarantuje zobrazenie foreground notifikácie v media controls oblasti a môže odmietnuť `FOREGROUND_SERVICE_MEDIA_PLAYBACK` typ. `MediaSession` nemusí implementovať ovládanie prehrávania — stačí ju vytvoriť, nastaviť metadata (title, artist) a zavolať `setActive(true)`.

---

## Chybové stavy a správanie

| Situácia | Správanie |
|----------|-----------|
| Server nie je zapnutý pri štarte | Discovery čaká 10s, opakuje každých 5s; stream sa pokúša pripojiť (LibVLC čaká na pakety) |
| Server sa vypne počas prehrávania | LibVLC stíchne; metadata poller po 3 zlyhaniach → re-discovery; UI: "Server nedostupný" |
| IP servera sa zmení | Cached health check zlyhá → re-discovery cez beacon |
| Telefón sa zamkne | Foreground service pokračuje, nič sa nemení |
| Používateľ stlačí Stop | LibVLC.stop(), notifikácia sa zmení, UI zobrazí Play tlačidlo |
| Používateľ stlačí Play | LibVLC.play() s rovnakou URL |

---

## Obmedzenia MVP

- Žiadne ovládanie prehrávania zo Android strany (next/prev/pause na PC)
- Žiadny cover art
- Žiadny equalizer
- Len jedna obrazovka

---

## Súhrn zmien

| Časť | Zmena |
|------|-------|
| `music_player/beacon.py` | Nový súbor, ~40 riadkov |
| `app.pyw` | +2 riadky (start/stop beacon) |
| Android app | Nový projekt, Kotlin + Compose + LibVLC |
