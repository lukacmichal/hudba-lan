# Android LAN Music Client — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pridať UDP beacon na Windows server a vytvoriť Android app ktorá sa automaticky pripojí na multicast stream a zobrazí aktuálnu skladbu.

**Architecture:** Server broadcastuje svoju IP každé 2s cez UDP. Android app zistí IP (cached alebo cez beacon), okamžite spustí LibVLC prehrávanie multicast streamu, a každé 2s polluje HTTP API pre metadata. Prehrávanie beží v Android Foreground Service aj keď je appka minimalizovaná.

**Tech Stack:** Python (server beacon), Kotlin + Jetpack Compose + LibVLC Android + AndroidX Media (Android client)

---

## Štruktúra súborov

### Server (Python)
```
music_player/
  beacon.py          ← NOVÝ: UdpBeaconSender trieda
  app.py             ← ZMENA: start/stop beacon (+4 riadky)
```

### Android (nový projekt v /c/music/android/)
```
android/
  settings.gradle.kts
  build.gradle.kts
  gradle/
    libs.versions.toml
  app/
    build.gradle.kts
    src/main/
      AndroidManifest.xml
      java/sk/lanmusic/
        MainActivity.kt
        ui/
          PlayerScreen.kt
          PlayerViewModel.kt
        service/
          StreamService.kt
        discovery/
          UdpDiscoveryManager.kt
        metadata/
          MetadataPoller.kt
          NowPlayingState.kt
      res/
        values/
          strings.xml
```

---

## Chunk 1: Server — UDP Beacon

### Task 1: `music_player/beacon.py`

**Files:**
- Create: `music_player/beacon.py`

- [ ] **Step 1: Vytvor súbor `music_player/beacon.py`**

```python
from __future__ import annotations

import json
import socket
import threading

BEACON_PORT = 8766
BEACON_INTERVAL = 2.0


class UdpBeaconSender:
    """Každé 2 sekundy broadcastuje JSON s IP a API portom na UDP port 8766."""

    def __init__(self, api_port: int = 8765) -> None:
        self._api_port = api_port
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ip = _local_ip_address()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _run(self) -> None:
        payload = json.dumps({
            "service": "lan-music-player",
            "ip": self._ip,
            "apiPort": self._api_port,
        }).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            while not self._stop_event.wait(BEACON_INTERVAL):
                try:
                    sock.sendto(payload, ("255.255.255.255", BEACON_PORT))
                except OSError:
                    pass


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
```

- [ ] **Step 2: Overiť manuálne že beacon vysiela**

```python
# Spusti v Python konzole:
from music_player.beacon import UdpBeaconSender
import socket, time

b = UdpBeaconSender(api_port=8765)
b.start()

# Prijímač:
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", 8766))
sock.settimeout(5)
data, addr = sock.recvfrom(512)
print(data)  # očakávane: b'{"service": "lan-music-player", "ip": "...", "apiPort": 8765}'

b.stop()
```

Očakávaný výsledok: JSON packet prijatý do 3 sekúnd.

- [ ] **Step 3: Commit**

```bash
cd /c/music
git add music_player/beacon.py
git commit -m "feat: add UDP beacon sender for LAN server discovery"
```

---

### Task 2: Zapojiť beacon do `music_player/app.py`

**Files:**
- Modify: `music_player/app.py`

- [ ] **Step 1: Pridaj import a start/stop beacon**

Nájdi v `music_player/app.py` riadok:
```python
from music_player.metadata_server import NowPlayingServer
```

Pridaj pod neho:
```python
from music_player.beacon import UdpBeaconSender
```

Nájdi v `main()` za `api_server.start()` a `controller.set_api_url(...)`:
```python
    controller.set_api_url(api_server.now_playing_url)
```

Pridaj za to:
```python
    beacon = UdpBeaconSender(api_port=api_server.port)
    beacon.start()
```

Nájdi v `_cleanup()`:
```python
    def _cleanup() -> None:
        window.save_state()
        stream_manager.stop()
        api_server.stop()
```

Zmeň na:
```python
    def _cleanup() -> None:
        window.save_state()
        stream_manager.stop()
        api_server.stop()
        beacon.stop()
```

- [ ] **Step 2: Spusti appku a over že beacon beží**

```bash
cd /c/music
python app.pyw
```

V druhom termináli:
```python
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", 8766))
sock.settimeout(5)
data, _ = sock.recvfrom(512)
print(data)
```

Očakávané: JSON s IP tvojho PC.

- [ ] **Step 3: Commit**

```bash
git add music_player/app.py
git commit -m "feat: start UDP beacon alongside API server on app launch"
```

---

## Chunk 2: Android — Project Scaffold

### Task 3: Gradle a project štruktúra

**Files:**
- Create: `android/settings.gradle.kts`
- Create: `android/build.gradle.kts`
- Create: `android/gradle/libs.versions.toml`
- Create: `android/app/build.gradle.kts`

> **Prerekvizita:** Android Studio nainštalované.
> **Povinný krok pred všetkým:** Otvor Android Studio → New Project → Empty Activity, nastav package name `sk.lanmusic`, jazyk Kotlin, min SDK 21, ulož do `/c/music/android/`. Toto vygeneruje Gradle wrapper (`gradlew`, `gradle/wrapper/`) ktorý je potrebný pre všetky `./gradlew` príkazy. Potom nahraď vygenerované build súbory nasledujúcimi.

- [ ] **Step 1: Vytvor `android/settings.gradle.kts`**

```kotlin
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "LanMusicClient"
include(":app")
```

- [ ] **Step 2: Vytvor `android/gradle/libs.versions.toml`**

```toml
[versions]
agp = "8.3.2"
kotlin = "2.0.0"
coreKtx = "1.13.1"
lifecycleRuntime = "2.8.2"
activityCompose = "1.9.0"
composeBom = "2024.06.00"
libvlc = "3.6.0"
media = "1.7.0"
coroutines = "1.8.1"

[libraries]
androidx-core-ktx = { group = "androidx.core", name = "core-ktx", version.ref = "coreKtx" }
androidx-lifecycle-runtime-ktx = { group = "androidx.lifecycle", name = "lifecycle-runtime-ktx", version.ref = "lifecycleRuntime" }
androidx-lifecycle-viewmodel-compose = { group = "androidx.lifecycle", name = "lifecycle-viewmodel-compose", version.ref = "lifecycleRuntime" }
androidx-activity-compose = { group = "androidx.activity", name = "activity-compose", version.ref = "activityCompose" }
compose-bom = { group = "androidx.compose", name = "compose-bom", version.ref = "composeBom" }
compose-ui = { group = "androidx.compose.ui", name = "ui" }
compose-ui-graphics = { group = "androidx.compose.ui", name = "ui-graphics" }
compose-material3 = { group = "androidx.compose.material3", name = "material3" }
libvlc = { group = "org.videolan.android", name = "libvlc-all", version.ref = "libvlc" }
androidx-media = { group = "androidx.media", name = "media", version.ref = "media" }  # poskytuje MediaSessionCompat + androidx.media.app.NotificationCompat.MediaStyle
kotlinx-coroutines-android = { group = "org.jetbrains.kotlinx", name = "kotlinx-coroutines-android", version.ref = "coroutines" }

[plugins]
android-application = { id = "com.android.application", version.ref = "agp" }
kotlin-android = { id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }
kotlin-compose = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
```

- [ ] **Step 3: Vytvor `android/build.gradle.kts` (root)**

```kotlin
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
}
```

- [ ] **Step 4: Vytvor `android/app/build.gradle.kts`**

```kotlin
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "sk.lanmusic"
    compileSdk = 35

    defaultConfig {
        applicationId = "sk.lanmusic"
        minSdk = 21
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.material3)
    implementation(libs.libvlc)
    implementation(libs.androidx.media)
    implementation(libs.kotlinx.coroutines.android)
}
```

- [ ] **Step 5: Vytvor `android/app/src/main/AndroidManifest.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK" />
    <uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE" />

    <application
        android:allowBackup="true"
        android:label="LAN Music"
        android:theme="@style/Theme.Material3.DayNight.NoActionBar">

        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <service
            android:name=".service.StreamService"
            android:foregroundServiceType="mediaPlayback" />

    </application>

</manifest>
```

- [ ] **Step 6: Vytvor `android/app/src/main/res/values/strings.xml`**

```xml
<resources>
    <string name="app_name">LAN Music</string>
</resources>
```

- [ ] **Step 7: Over že projekt kompiluje (prázdne stubs)**

```bash
cd /c/music/android
./gradlew assembleDebug
```

Očakávané: BUILD SUCCESSFUL (pred pridaním Kotlin súborov — len scaffold).

- [ ] **Step 8: Commit**

```bash
cd /c/music
git add android/
git commit -m "feat: scaffold Android project with LibVLC and Compose dependencies"
```

---

## Chunk 3: Android — Dátové modely, Discovery, Metadata

### Task 4: `NowPlayingState.kt` a `DiscoveryState`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/metadata/NowPlayingState.kt`
- Create: `android/app/src/main/java/sk/lanmusic/discovery/DiscoveryState.kt`
- Create: `android/app/src/main/java/sk/lanmusic/service/PlaybackState.kt`

- [ ] **Step 1: Vytvor `metadata/NowPlayingState.kt`**

```kotlin
package sk.lanmusic.metadata

data class NowPlayingState(
    val title: String = "",
    val artist: String = "",
    val state: String = "stopped",
    val streamingActive: Boolean = false,
)
```

- [ ] **Step 2: Vytvor `discovery/DiscoveryState.kt`**

```kotlin
package sk.lanmusic.discovery

sealed class DiscoveryState {
    object Discovering : DiscoveryState()
    data class Found(val ip: String, val port: Int) : DiscoveryState()
    object NotFound : DiscoveryState()
}
```

- [ ] **Step 3: Vytvor `service/PlaybackState.kt`**

```kotlin
package sk.lanmusic.service

sealed class PlaybackState {
    object Playing : PlaybackState()
    object Stopped : PlaybackState()
    object Error : PlaybackState()
}
```

- [ ] **Step 4: Commit**

```bash
git add android/app/src/main/java/
git commit -m "feat: add state data classes for discovery, metadata, playback"
```

---

### Task 5: `UdpDiscoveryManager.kt`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/discovery/UdpDiscoveryManager.kt`

- [ ] **Step 1: Vytvor `discovery/UdpDiscoveryManager.kt`**

```kotlin
package sk.lanmusic.discovery

import android.content.Context
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONException
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.URL

private const val BEACON_PORT = 8766
private const val HEALTH_TIMEOUT_MS = 2_000
private const val BEACON_TIMEOUT_MS = 10_000
private const val RETRY_DELAY_MS = 5_000L
private const val PREFS_NAME = "lan_music_prefs"
private const val PREF_IP = "server_ip"
private const val PREF_PORT = "server_port"
private const val EXPECTED_SERVICE = "lan-music-player"

class UdpDiscoveryManager(private val context: Context) {

    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private val _state = MutableStateFlow<DiscoveryState>(DiscoveryState.Discovering)
    val state: StateFlow<DiscoveryState> = _state

    private var job: Job? = null

    /** Spustí discovery. clearCache=true vymaže uloženú IP a vynúti beacon scan. */
    fun start(clearCache: Boolean = false) {
        if (clearCache) {
            prefs.edit().remove(PREF_IP).remove(PREF_PORT).apply()
        }
        job?.cancel()
        job = scope.launch { runDiscovery() }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    private suspend fun runDiscovery() {
        _state.value = DiscoveryState.Discovering

        // 1. Skús cached IP
        val cachedIp = prefs.getString(PREF_IP, null)
        val cachedPort = prefs.getInt(PREF_PORT, 8765)
        if (cachedIp != null && checkHealth(cachedIp, cachedPort)) {
            _state.value = DiscoveryState.Found(cachedIp, cachedPort)
            return
        }

        // 2. Beacon scan, opakuj každých 5s pokiaľ nenájde
        while (isActive) {
            val result = listenForBeacon()
            if (result != null) {
                val (ip, port) = result
                prefs.edit().putString(PREF_IP, ip).putInt(PREF_PORT, port).apply()
                _state.value = DiscoveryState.Found(ip, port)
                return
            }
            _state.value = DiscoveryState.NotFound
            delay(RETRY_DELAY_MS)
            _state.value = DiscoveryState.Discovering
        }
    }

    private fun checkHealth(ip: String, port: Int): Boolean {
        return try {
            val conn = URL("http://$ip:$port/health").openConnection() as HttpURLConnection
            conn.connectTimeout = HEALTH_TIMEOUT_MS
            conn.readTimeout = HEALTH_TIMEOUT_MS
            val code = conn.responseCode
            conn.disconnect()
            code == 200
        } catch (_: Exception) {
            false
        }
    }

    /** Čaká max 10s na beacon packet. Vráti (ip, port) alebo null ak timeout. */
    private fun listenForBeacon(): Pair<String, Int>? {
        val buf = ByteArray(512)
        val packet = DatagramPacket(buf, buf.size)
        return try {
            DatagramSocket(null).use { sock ->
                sock.reuseAddress = true
                sock.bind(InetSocketAddress(BEACON_PORT))  // port-only = wildcard 0.0.0.0, bezpečné na všetkých Android kerneloch
                sock.broadcast = true
                sock.soTimeout = BEACON_TIMEOUT_MS
                // Čakaj v slučke — môžu prísť cudzie pakety na tom istom porte
                while (true) {
                    sock.receive(packet)
                    val parsed = parseBeacon(packet) ?: continue
                    return parsed
                }
                @Suppress("UNREACHABLE_CODE")
                null
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun parseBeacon(packet: DatagramPacket): Pair<String, Int>? {
        return try {
            val text = String(packet.data, 0, packet.length, Charsets.UTF_8)
            val json = JSONObject(text)
            if (json.optString("service") != EXPECTED_SERVICE) return null
            val ip = json.getString("ip")
            val port = json.getInt("apiPort")
            if (ip.isBlank()) return null
            Pair(ip, port)
        } catch (_: JSONException) {
            null
        } catch (_: Exception) {
            null
        }
    }
}
```

- [ ] **Step 2: Over kompilovanosť**

```bash
cd /c/music/android
./gradlew :app:compileDebugKotlin
```

Očakávané: BUILD SUCCESSFUL, žiadne chyby.

- [ ] **Step 3: Commit**

```bash
cd /c/music
git add android/app/src/main/java/sk/lanmusic/discovery/
git commit -m "feat: implement UDP discovery manager with cache and beacon fallback"
```

---

### Task 6: `MetadataPoller.kt`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/metadata/MetadataPoller.kt`

- [ ] **Step 1: Vytvor `metadata/MetadataPoller.kt`**

```kotlin
package sk.lanmusic.metadata

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val POLL_INTERVAL_MS = 2_000L
private const val REQUEST_TIMEOUT_MS = 3_000
private const val MAX_FAILURES = 3

class MetadataPoller(private val ip: String, private val port: Int) {

    private val _nowPlaying = MutableStateFlow(NowPlayingState())
    val nowPlaying: StateFlow<NowPlayingState> = _nowPlaying

    private val _serverLost = MutableStateFlow(false)
    val serverLost: StateFlow<Boolean> = _serverLost

    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        job = scope.launch(Dispatchers.IO) {
            var failures = 0
            while (isActive) {
                val result = fetchNowPlaying()
                if (result != null) {
                    failures = 0
                    _nowPlaying.value = result
                } else {
                    failures++
                    if (failures >= MAX_FAILURES) {
                        _serverLost.value = true
                        return@launch
                    }
                }
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    private fun fetchNowPlaying(): NowPlayingState? {
        return try {
            val conn = URL("http://$ip:$port/api/now-playing").openConnection() as HttpURLConnection
            conn.connectTimeout = REQUEST_TIMEOUT_MS
            conn.readTimeout = REQUEST_TIMEOUT_MS
            if (conn.responseCode != 200) {
                conn.disconnect()
                return null
            }
            val body = conn.inputStream.bufferedReader().readText()
            conn.disconnect()
            val json = JSONObject(body)
            NowPlayingState(
                title = json.optString("title"),
                artist = json.optString("artist"),
                state = json.optString("state", "stopped"),
                streamingActive = json.optBoolean("streamingActive", false),
            )
        } catch (_: Exception) {
            null
        }
    }
}
```

- [ ] **Step 2: Over kompilovanosť**

```bash
cd /c/music/android
./gradlew :app:compileDebugKotlin
```

- [ ] **Step 3: Commit**

```bash
cd /c/music
git add android/app/src/main/java/sk/lanmusic/metadata/
git commit -m "feat: implement metadata poller with server-lost detection"
```

---

## Chunk 4: Android — StreamService

### Task 7: `StreamService.kt`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/service/StreamService.kt`

- [ ] **Step 1: Vytvor `service/StreamService.kt`**

```kotlin
package sk.lanmusic.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.media.app.NotificationCompat.MediaStyle
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.videolan.libvlc.LibVLC
import org.videolan.libvlc.Media
import org.videolan.libvlc.MediaPlayer
import sk.lanmusic.MainActivity

private const val CHANNEL_ID = "lan_music_channel"
private const val NOTIFICATION_ID = 1
private const val STREAM_URL =
    "udp://@239.255.12.42:5004?fifo_size=1000000&overrun_nonfatal=1"
private const val ACTION_STOP = "sk.lanmusic.ACTION_STOP"
private const val ACTION_PLAY = "sk.lanmusic.ACTION_PLAY"

class StreamService : Service() {

    inner class LocalBinder : Binder() {
        fun getService(): StreamService = this@StreamService
    }

    private val binder = LocalBinder()
    private lateinit var libVlc: LibVLC
    private lateinit var mediaPlayer: MediaPlayer
    private lateinit var mediaSession: MediaSessionCompat
    private var multicastLock: WifiManager.MulticastLock? = null

    private val _playbackState = MutableStateFlow<PlaybackState>(PlaybackState.Stopped)
    val playbackState: StateFlow<PlaybackState> = _playbackState

    private var currentTitle = ""
    private var currentArtist = ""

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        acquireMulticastLock()
        initLibVlc()
        initMediaSession()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Musíme zavolať startForeground okamžite, inak Android 12+ hodí exception
        startForeground(NOTIFICATION_ID, buildNotification())
        when (intent?.action) {
            ACTION_STOP -> stop()
            ACTION_PLAY -> play()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent): IBinder = binder

    override fun onDestroy() {
        mediaPlayer.stop()
        mediaPlayer.release()
        libVlc.release()
        mediaSession.release()
        multicastLock?.release()
        super.onDestroy()
    }

    fun play() {
        val media = Media(libVlc, Uri.parse(STREAM_URL))
        mediaPlayer.media = media
        media.release()
        mediaPlayer.play()
        _playbackState.value = PlaybackState.Playing
        updateMediaSessionState(isPlaying = true)
        updateNotificationAndPost()
    }

    fun stop() {
        mediaPlayer.stop()
        _playbackState.value = PlaybackState.Stopped
        updateMediaSessionState(isPlaying = false)
        updateNotificationAndPost()
    }

    fun updateNowPlaying(title: String, artist: String) {
        currentTitle = title
        currentArtist = artist
        updateNotificationAndPost()
        mediaSession.setMetadata(
            MediaMetadataCompat.Builder()
                .putString(MediaMetadataCompat.METADATA_KEY_TITLE, title)
                .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, artist)
                .build()
        )
    }

    private fun initLibVlc() {
        val options = arrayListOf(
            "--network-caching=150",
            "--no-video",
            "--aout=opensles",
        )
        libVlc = LibVLC(this, options)
        mediaPlayer = MediaPlayer(libVlc)
    }

    private fun initMediaSession() {
        mediaSession = MediaSessionCompat(this, "LanMusicSession")
        mediaSession.setActive(true)
        updateMediaSessionState(isPlaying = false)
    }

    private fun updateMediaSessionState(isPlaying: Boolean) {
        val stateVal = if (isPlaying)
            PlaybackStateCompat.STATE_PLAYING
        else
            PlaybackStateCompat.STATE_STOPPED
        mediaSession.setPlaybackState(
            PlaybackStateCompat.Builder()
                .setState(stateVal, 0L, 1f)
                .build()
        )
    }

    private fun acquireMulticastLock() {
        val wifiManager =
            applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        multicastLock = wifiManager.createMulticastLock("lan-music").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "LAN Music",
                NotificationManager.IMPORTANCE_LOW
            ).apply { description = "LAN Music playback" }
            getSystemService(NotificationManager::class.java)
                .createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        val openIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        val isPlaying = _playbackState.value is PlaybackState.Playing
        val actionIntent = if (isPlaying) {
            PendingIntent.getService(
                this, 0,
                Intent(this, StreamService::class.java).apply { action = ACTION_STOP },
                PendingIntent.FLAG_IMMUTABLE
            )
        } else {
            PendingIntent.getService(
                this, 1,
                Intent(this, StreamService::class.java).apply { action = ACTION_PLAY },
                PendingIntent.FLAG_IMMUTABLE
            )
        }

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(currentTitle.ifEmpty { "LAN Music" })
            .setContentText(currentArtist)
            .setContentIntent(openIntent)
            .addAction(
                if (isPlaying) android.R.drawable.ic_media_pause
                else android.R.drawable.ic_media_play,
                if (isPlaying) "Stop" else "Prehrať",
                actionIntent
            )
            .setStyle(
                MediaStyle()
                    .setMediaSession(mediaSession.sessionToken)
                    .setShowActionsInCompactView(0)
            )
            .setOngoing(isPlaying)
            .build()
    }

    private fun updateNotificationAndPost() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification())
    }
}
```

- [ ] **Step 2: Over kompilovanosť**

```bash
cd /c/music/android
./gradlew :app:compileDebugKotlin
```

- [ ] **Step 3: Commit**

```bash
cd /c/music
git add android/app/src/main/java/sk/lanmusic/service/
git commit -m "feat: implement StreamService with LibVLC, MulticastLock, MediaSession"
```

---

## Chunk 5: Android — ViewModel a UI

### Task 8: `PlayerViewModel.kt`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/ui/PlayerViewModel.kt`

- [ ] **Step 1: Vytvor `ui/PlayerViewModel.kt`**

```kotlin
package sk.lanmusic.ui

import android.app.Application
import android.content.ComponentName
import android.content.ServiceConnection
import android.os.IBinder
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import sk.lanmusic.discovery.DiscoveryState
import sk.lanmusic.discovery.UdpDiscoveryManager
import sk.lanmusic.metadata.MetadataPoller
import sk.lanmusic.metadata.NowPlayingState
import sk.lanmusic.service.PlaybackState
import sk.lanmusic.service.StreamService

data class PlayerUiState(
    val discovery: DiscoveryState = DiscoveryState.Discovering,
    val nowPlaying: NowPlayingState = NowPlayingState(),
    val playback: PlaybackState = PlaybackState.Stopped,
)

class PlayerViewModel(application: Application) : AndroidViewModel(application) {

    private val discoveryManager = UdpDiscoveryManager(application)
    private var metadataPoller: MetadataPoller? = null
    private var streamService: StreamService? = null

    private val _uiState = MutableStateFlow(PlayerUiState())
    val uiState: StateFlow<PlayerUiState> = _uiState.asStateFlow()

    private var isFirstConnection = true

    val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            val service = (binder as StreamService.LocalBinder).getService()
            streamService = service
            // Spusti prehrávanie len pri prvom pripojení (nie pri každom onStart/resume)
            if (isFirstConnection) {
                isFirstConnection = false
                service.play()
            }
            viewModelScope.launch {
                service.playbackState.collect { state ->
                    _uiState.update { it.copy(playback = state) }
                }
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            streamService = null
        }
    }

    init {
        observeDiscovery()
        discoveryManager.start()
    }

    fun onPlayClicked() {
        streamService?.play()
    }

    fun onStopClicked() {
        streamService?.stop()
    }

    fun onReconnectClicked() {
        discoveryManager.start(clearCache = true)
    }

    private fun observeDiscovery() {
        viewModelScope.launch {
            discoveryManager.state.collect { discovery ->
                _uiState.update { it.copy(discovery = discovery) }
                if (discovery is DiscoveryState.Found) {
                    startMetadataPoller(discovery.ip, discovery.port)
                }
            }
        }
    }

    private fun startMetadataPoller(ip: String, port: Int) {
        metadataPoller?.stop()
        val poller = MetadataPoller(ip, port)
        metadataPoller = poller
        poller.start(viewModelScope)

        viewModelScope.launch {
            poller.nowPlaying.collect { nowPlaying ->
                _uiState.update { it.copy(nowPlaying = nowPlaying) }
                streamService?.updateNowPlaying(nowPlaying.title, nowPlaying.artist)
            }
        }

        // Sleduj serverLost — pri strate spusti re-discovery
        viewModelScope.launch {
            poller.serverLost.filter { it }.collect {
                metadataPoller?.stop()
                metadataPoller = null
                discoveryManager.start(clearCache = true)
            }
        }
    }

    override fun onCleared() {
        discoveryManager.stop()
        metadataPoller?.stop()
        super.onCleared()
    }
}
```

- [ ] **Step 2: Commit**

```bash
cd /c/music
git add android/app/src/main/java/sk/lanmusic/ui/PlayerViewModel.kt
git commit -m "feat: implement PlayerViewModel coordinating discovery, metadata, service"
```

---

### Task 9: `PlayerScreen.kt` a `MainActivity.kt`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/ui/PlayerScreen.kt`
- Create: `android/app/src/main/java/sk/lanmusic/MainActivity.kt`

- [ ] **Step 1: Vytvor `ui/PlayerScreen.kt`**

```kotlin
package sk.lanmusic.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import sk.lanmusic.discovery.DiscoveryState
import sk.lanmusic.service.PlaybackState

@Composable
fun PlayerScreen(
    uiState: PlayerUiState,
    onPlayClicked: () -> Unit,
    onStopClicked: () -> Unit,
    onReconnectClicked: () -> Unit,
) {
    val isPlaying = uiState.playback is PlaybackState.Playing
    val isDiscovering = uiState.discovery is DiscoveryState.Discovering
    val isNotFound = uiState.discovery is DiscoveryState.NotFound

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        // Status chip hore
        StatusChip(discovery = uiState.discovery, isPlaying = isPlaying)

        // Stred: názov a interpret
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.weight(1f),
        ) {
            Text(
                text = uiState.nowPlaying.title.ifEmpty { "—" },
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center,
                lineHeight = 34.sp,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                text = uiState.nowPlaying.artist,
                fontSize = 18.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }

        // Dole: tlačidlo + stream info
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            when {
                isNotFound -> Button(onClick = onReconnectClicked) {
                    Text("Reconnect")
                }
                isPlaying -> Button(
                    onClick = onStopClicked,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error
                    )
                ) {
                    Text("■  Stop")
                }
                !isDiscovering -> Button(onClick = onPlayClicked) {
                    Text("▶  Prehrať")
                }
                else -> {
                    // Počas discovery len spinner
                    CircularProgressIndicator(modifier = Modifier.size(40.dp))
                }
            }
            Spacer(Modifier.height(20.dp))
            Text(
                text = "udp://239.255.12.42:5004",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}

@Composable
private fun StatusChip(discovery: DiscoveryState, isPlaying: Boolean) {
    val (label, color) = when {
        discovery is DiscoveryState.NotFound ->
            "Server nedostupný" to Color(0xFFE53935)
        discovery is DiscoveryState.Discovering ->
            "Hľadám server..." to Color(0xFFFFA000)
        isPlaying ->
            "Pripojené" to Color(0xFF43A047)
        else ->
            "Zastavené" to Color(0xFF9E9E9E)
    }

    val isPulsing = discovery is DiscoveryState.Discovering
    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val scale by if (isPulsing) {
        infiniteTransition.animateFloat(
            initialValue = 0.7f,
            targetValue = 1.3f,
            animationSpec = infiniteRepeatable(
                animation = tween(600),
                repeatMode = RepeatMode.Reverse
            ),
            label = "dot_scale",
        )
    } else {
        remember { mutableStateOf(1f) }
    }

    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(10.dp)
                .scale(scale)
                .background(color, CircleShape)
        )
        Spacer(Modifier.width(8.dp))
        Text(label, fontSize = 14.sp, color = color)
    }
}
```

- [ ] **Step 2: Vytvor `MainActivity.kt`**

```kotlin
package sk.lanmusic

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.core.content.ContextCompat
import sk.lanmusic.service.StreamService
import sk.lanmusic.ui.PlayerScreen
import sk.lanmusic.ui.PlayerViewModel

class MainActivity : ComponentActivity() {

    private val viewModel: PlayerViewModel by viewModels()
    private var isBound = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface {
                    val uiState by viewModel.uiState.collectAsState()
                    PlayerScreen(
                        uiState = uiState,
                        onPlayClicked = viewModel::onPlayClicked,
                        onStopClicked = viewModel::onStopClicked,
                        onReconnectClicked = viewModel::onReconnectClicked,
                    )
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        // Najprv startForegroundService (service prežije unbind),
        // potom bindService pre priamu komunikáciu
        val intent = Intent(this, StreamService::class.java)
        ContextCompat.startForegroundService(this, intent)
        isBound = bindService(intent, viewModel.serviceConnection, BIND_AUTO_CREATE)
    }

    override fun onStop() {
        super.onStop()
        // Volaj unbindService len ak bind prebehol úspešne
        if (isBound) {
            unbindService(viewModel.serviceConnection)
            isBound = false
        }
    }
}
```

- [ ] **Step 3: Over kompiláciu celého projektu**

```bash
cd /c/music/android
./gradlew assembleDebug
```

Očakávané: `BUILD SUCCESSFUL`, vygenerovaný `app/build/outputs/apk/debug/app-debug.apk`.

- [ ] **Step 4: Commit**

```bash
cd /c/music
git add android/app/src/main/java/sk/lanmusic/
git commit -m "feat: implement PlayerScreen Compose UI and MainActivity lifecycle"
```

---

## Chunk 6: Integračné testovanie

### Task 10: End-to-end test na reálnom zariadení

- [ ] **Step 1: Spusti Windows appku**

```bash
cd /c/music
python app.pyw
```

Nahraj do playlistu nejaký MP3/FLAC a stlač Play. Over:
- V stavovom riadku appky: `Streaming: ON`
- API odpovedá: `curl http://localhost:8765/api/now-playing`
- Beacon beží: `python -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('0.0.0.0',8766)); s.settimeout(5); print(s.recvfrom(512))"`

- [ ] **Step 2: Inštaluj APK na Android telefón**

```bash
# Telefón musí mať USB debugging zapnuté
adb install /c/music/android/app/build/outputs/apk/debug/app-debug.apk
```

Alebo: v Android Studio → Run → vyberi zariadenie.

- [ ] **Step 3: Over správanie**

Spusti appku na telefóne. Očakávaný priebeh:
1. Zobrazí `● Hľadám server...` (žltý)
2. Do 3s: prechod na `● Pripojené` (zelený), stream začne hrať
3. Zobrazí sa názov skladby a interpret z API
4. Minimalizuj appku — hudba hrá ďalej
5. Zamkni telefón — hudba hrá ďalej
6. Rozbal notifikáciu — vidíš názov skladby + Stop tlačidlo
7. Stlač Stop v notifikácii — hudba stíchne, UI ukáže `▶ Prehrať`

- [ ] **Step 4: Over re-discovery**

1. Appka hrá, server beží
2. Zatvori Windows appku
3. Počkaj ~8s — Android UI ukáže `● Server nedostupný` (červený)
4. Znova spusti Windows appku
5. Do 15s — Android sa automaticky reconnectne

- [ ] **Step 5: Záverečný commit**

```bash
cd /c/music
git add .
git commit -m "feat: complete Android LAN music client MVP"
```

---

## Zhrnutie

| Chunk | Obsah | Výsledok |
|-------|-------|----------|
| 1 | Server beacon | UDP broadcast každé 2s |
| 2 | Android scaffold | Gradle + Manifest + závislosti |
| 3 | Discovery + Metadata | IP auto-discovery, now-playing polling |
| 4 | StreamService | LibVLC multicast + foreground notifikácia |
| 5 | ViewModel + UI | Compose UI, životný cyklus |
| 6 | Integračné testy | End-to-end na reálnom zariadení |
