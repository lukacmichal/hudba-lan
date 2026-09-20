package sk.lanmusic.ui

import android.app.Application
import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.os.Build
import android.os.IBinder
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import sk.lanmusic.control.RemoteControlClient
import sk.lanmusic.discovery.DiscoveryState
import sk.lanmusic.discovery.DEFAULT_API_PORT
import sk.lanmusic.widget.OvladacPrefs
import sk.lanmusic.widget.OvladacWidgetProvider
import sk.lanmusic.discovery.UdpDiscoveryManager
import sk.lanmusic.metadata.MetadataPoller
import sk.lanmusic.metadata.NowPlayingState
import sk.lanmusic.playlist.PlaylistItem
import sk.lanmusic.playlist.PlaylistRepository
import sk.lanmusic.service.ACTION_EXIT
import sk.lanmusic.service.PlaybackState
import sk.lanmusic.service.StreamService
import sk.lanmusic.update.ApkInstaller
import sk.lanmusic.update.SmbUpdateSource
import sk.lanmusic.update.UpdateChecker
import sk.lanmusic.update.UpdateConfig
import sk.lanmusic.update.UpdateSettingsStore
import sk.lanmusic.update.UpdateState

data class PlayerUiState(
    val discovery: DiscoveryState = DiscoveryState.Discovering,
    val nowPlaying: NowPlayingState = NowPlayingState(),
    val playback: PlaybackState = PlaybackState.Stopped,
    val playlist: List<PlaylistItem> = emptyList(),
    val updateState: UpdateState = UpdateState.Idle,
    val updateConfig: UpdateConfig = UpdateConfig(),
    /** Rucne zadana adresa prehravaca; prazdna = appka si ho hlada sama. */
    val manualServerIp: String = "",
    val manualServerPort: Int = DEFAULT_API_PORT,
    val appVersion: String = "",
    /** What the NAS reports, "1.3.4 (8)" — null until a check succeeds. */
    val remoteVersion: String? = null,
) {
    val streamingActive: Boolean get() = nowPlaying.streamingActive
    val streamUrl: String get() = nowPlaying.streamUrl
    /** True while the phone receives (or is connecting to) the audio stream. */
    val listening: Boolean
        get() = playback is PlaybackState.Playing || playback is PlaybackState.Connecting
}

class PlayerViewModel(application: Application) : AndroidViewModel(application) {

    private val discoveryManager = UdpDiscoveryManager(application)
    private var metadataPoller: MetadataPoller? = null
    private var streamService: StreamService? = null

    private var controlClient: RemoteControlClient? = null
    private var serverIp: String = ""
    private var serverPort: Int = 0
    private var lastPlaylistVersion: Int = -1
    private var playlistFetchInFlight: Boolean = false
    private var prevStreamingActive: Boolean = false
    private var volumeBeforeMute: Int = 50

    private val settingsStore = UpdateSettingsStore(application)
    private val installer = ApkInstaller(application)
    private val updateChecker = UpdateChecker(
        source = SmbUpdateSource(),
        cacheDir = application.cacheDir,
        currentVersionCode = { installedVersionCode() },
    )
    private var updateCheckJob: Job? = null

    // Streaming to the phone is opt-in: the app starts as a pure remote and
    // only receives audio after the user turns listening on.
    private var listeningEnabled: Boolean = false

    private val _uiState = MutableStateFlow(PlayerUiState())
    val uiState: StateFlow<PlayerUiState> = _uiState.asStateFlow()

    private var playbackCollectJob: Job? = null

    val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            val service = (binder as StreamService.LocalBinder).getService()
            streamService = service
            // The activity re-binds on every onStart — replace the previous
            // collector instead of stacking a new one per bind.
            playbackCollectJob?.cancel()
            playbackCollectJob = viewModelScope.launch {
                service.playbackState.collect { state ->
                    _uiState.update { it.copy(playback = state) }
                }
            }
            if (serverIp.isNotEmpty()) {
                service.configureRemote(serverIp, serverPort)
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            playbackCollectJob?.cancel()
            playbackCollectJob = null
            streamService = null
        }
    }

    init {
        observeDiscovery()
        discoveryManager.start()

        _uiState.update {
            it.copy(
                updateConfig = settingsStore.load(),
                manualServerIp = discoveryManager.manualServer()?.first.orEmpty(),
                manualServerPort = discoveryManager.manualServer()?.second ?: DEFAULT_API_PORT,
                appVersion = installedVersionName(),
            )
        }
        viewModelScope.launch {
            updateChecker.state.collect { s -> _uiState.update { it.copy(updateState = s) } }
        }
        viewModelScope.launch {
            updateChecker.remote.collect { m ->
                _uiState.update {
                    it.copy(remoteVersion = m?.let { r -> "${r.versionName} (${r.versionCode})" })
                }
            }
        }
        checkForUpdates(silent = true)
    }

    /**
     * Pulls the APK the last check found. Separate from [checkForUpdates] so the
     * ~50 MB download only starts after the user says yes (docs/shared-standard.md 2.4).
     */
    fun onConfirmUpdate() {
        val s = _uiState.value.updateState
        if (s !is UpdateState.Available) return
        updateCheckJob?.cancel()
        updateCheckJob = viewModelScope.launch {
            updateChecker.download(_uiState.value.updateConfig, s.manifest)
        }
    }

    // ── self-update ──────────────────────────────────────────────────────────
    /**
     * @param silent startup check — an unreachable NAS must never nag the user,
     *               so failures are swallowed. Manual checks surface everything.
     */
    fun checkForUpdates(silent: Boolean = false) {
        updateCheckJob?.cancel()
        updateCheckJob = viewModelScope.launch {
            val cfg = _uiState.value.updateConfig
            if (silent && !cfg.isComplete) return@launch
            updateChecker.check(cfg)
            if (silent && updateChecker.state.value is UpdateState.Failed) {
                updateChecker.reset()
            }
        }
    }

    /**
     * Ulozi rucnu adresu prehravaca a hned podla nej hlada znova.
     *
     * Prazdna adresa vrati appku k automatickemu vyhladavaniu — vtedy sa
     * `clearCache` hodi, aby sa nechytila stara ulozena IP z ineho miesta.
     */
    fun onManualServerSaved(ip: String, port: Int) {
        discoveryManager.saveManualServer(ip, port)
        val ulozene = discoveryManager.manualServer()
        _uiState.update {
            it.copy(
                manualServerIp = ulozene?.first.orEmpty(),
                manualServerPort = ulozene?.second ?: DEFAULT_API_PORT,
            )
        }
        discoveryManager.start(clearCache = ulozene == null)
    }

    fun onUpdateSettingsSaved(cfg: UpdateConfig) {
        settingsStore.save(cfg)
        _uiState.update { it.copy(updateConfig = cfg) }
    }

    /** Backs the "Otestovať spojenie" button; returns a message to display. */
    suspend fun testConnection(cfg: UpdateConfig): String = try {
        val m = SmbUpdateSource().fetchManifest(cfg)
        if (m == null) {
            "Prihlásenie OK. latest.json tam zatiaľ nie je — objaví sa po prvom publishi."
        } else {
            "OK — na NASe je verzia ${m.versionName}."
        }
    } catch (e: Exception) {
        "Chyba: ${e.message ?: e::class.simpleName}"
    }

    fun onInstallUpdate() {
        val s = _uiState.value.updateState
        if (s !is UpdateState.ReadyToInstall) return
        if (!installer.canInstall()) {
            installer.requestPermission()
            return
        }
        installer.install(s.file)
    }

    fun onDismissUpdate() = updateChecker.reset()

    @Suppress("DEPRECATION")
    private fun installedVersionCode(): Long {
        val app = getApplication<Application>()
        val info = app.packageManager.getPackageInfo(app.packageName, 0)
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            info.longVersionCode
        } else {
            info.versionCode.toLong()
        }
    }

    private fun installedVersionName(): String {
        val app = getApplication<Application>()
        return app.packageManager.getPackageInfo(app.packageName, 0).versionName ?: ""
    }

    // ── remote control (controls the PC player) ──────────────────────────────
    fun onPrev() = sendControl { it.prev() }
    fun onNext() = sendControl { it.next() }
    fun onStopRemote() = sendControl { it.stop() }
    fun onSeek(positionMs: Long) = sendControl { it.seek(positionMs) }
    fun onPlayIndex(index: Int) = sendControl { it.playIndex(index) }
    fun onShutdown() = sendControl { it.shutdown() }
    fun onSleep() = sendControl { it.sleep() }
    fun onSleep2() = sendControl { it.sleep2() }

    fun onVolume(value: Int) {
        // Optimistic so the slider doesn't snap back before the next poll.
        _uiState.update { it.copy(nowPlaying = it.nowPlaying.copy(volume = value)) }
        sendControl { it.setVolume(value) }
    }

    fun onToggleMute() {
        val current = _uiState.value.nowPlaying.volume
        val target = if (current > 0) {
            volumeBeforeMute = current
            0
        } else {
            if (volumeBeforeMute > 0) volumeBeforeMute else 50
        }
        onVolume(target)
    }

    fun onPlayPause() {
        // Optimistic flip; reconciled by the next metadata poll.
        _uiState.update {
            val flipped = if (it.nowPlaying.state == "playing") "paused" else "playing"
            it.copy(nowPlaying = it.nowPlaying.copy(state = flipped))
        }
        sendControl { it.playPause() }
    }

    private fun sendControl(block: suspend (RemoteControlClient) -> Unit) {
        val client = controlClient ?: return
        viewModelScope.launch { block(client) }
    }

    // ── listening (receiving the stream on the phone) ────────────────────────
    fun onToggleListening() {
        val service = streamService ?: return
        if (_uiState.value.listening) {
            listeningEnabled = false
            service.stop()
        } else {
            val url = _uiState.value.streamUrl
            if (url.isNotEmpty() && _uiState.value.streamingActive) {
                listeningEnabled = true
                prevStreamingActive = true
                // Restore the service's started+foreground state in case the
                // user previously exited it from the notification while the
                // app stayed open (the binding kept the instance alive).
                val ctx = getApplication<Application>()
                ContextCompat.startForegroundService(
                    ctx, Intent(ctx, StreamService::class.java)
                )
                service.play(url)
            }
        }
    }

    // ── discovery / reconnect / exit ─────────────────────────────────────────
    fun onReconnectClicked() {
        discoveryManager.start(clearCache = true)
    }

    fun onExitClicked() {
        // exit() in the service stops playback itself; calling stop() here
        // first only fired extra async LibVLC events that re-posted the
        // notification after the service had already removed it.
        val ctx = getApplication<Application>()
        val intent = Intent(ctx, StreamService::class.java).apply { action = ACTION_EXIT }
        ctx.startService(intent)
        streamService = null
    }

    private fun observeDiscovery() {
        viewModelScope.launch {
            discoveryManager.state.collect { discovery ->
                _uiState.update { it.copy(discovery = discovery) }
                if (discovery is DiscoveryState.Found) {
                    serverIp = discovery.ip
                    serverPort = discovery.port
                    controlClient = RemoteControlClient(discovery.ip, discovery.port)
                    streamService?.configureRemote(discovery.ip, discovery.port)
                    startMetadataPoller(discovery.ip, discovery.port)
                    // Widget si adresu cita z toho isteho uloziska, ale text
                    // "Prehravac zatial nenajdeny" by na nom ostal az do
                    // dalsieho prekreslenia. Toto ho zmaze hned.
                    OvladacWidgetProvider.prekresliVsetky(getApplication())
                }
            }
        }
    }

    private fun startMetadataPoller(ip: String, port: Int) {
        metadataPoller?.stop()
        lastPlaylistVersion = -1
        prevStreamingActive = false
        val poller = MetadataPoller(ip, port)
        metadataPoller = poller
        poller.start(viewModelScope)

        viewModelScope.launch {
            poller.nowPlaying.collect { nowPlaying ->
                _uiState.update { it.copy(nowPlaying = nowPlaying) }
                streamService?.updateNowPlaying(
                    title = nowPlaying.title,
                    artist = nowPlaying.artist,
                    positionMs = nowPlaying.positionMs,
                    durationMs = nowPlaying.durationMs,
                    isServerPlaying = nowPlaying.state == "playing",
                    streamUrl = nowPlaying.streamUrl,
                )
                // Widget na ploche nema z coho nazov skladby zistit — sam
                // na siet nechodi. Zapisuje mu ho appka pri kazdom pollnuti,
                // takze widget ukazuje to, co appka videla naposledy.
                val ctx = getApplication<Application>()
                OvladacPrefs.ulozSkladbu(
                    ctx,
                    titul = nowPlaying.title,
                    interpret = nowPlaying.artist,
                    hra = nowPlaying.state == "playing",
                    hlasitost = nowPlaying.volume,
                )
                OvladacWidgetProvider.prekresliVsetky(ctx)
                followStream(nowPlaying.streamingActive, nowPlaying.streamUrl)
                maybeRefreshPlaylist(nowPlaying.playlistVersion)
            }
        }

        viewModelScope.launch {
            poller.serverLost.filter { it }.collect {
                metadataPoller?.stop()
                metadataPoller = null
                controlClient = null
                discoveryManager.start(clearCache = true)
            }
        }
    }

    /** While the user has listening turned on, mirror the PC stream state
     *  (reconnect when it comes back, stop when it goes away). Does nothing
     *  until the user starts listening manually. */
    private fun followStream(active: Boolean, url: String) {
        if (!listeningEnabled) {
            prevStreamingActive = active
            return
        }
        if (active && !prevStreamingActive && url.isNotEmpty()) {
            streamService?.play(url)
        } else if (!active && prevStreamingActive) {
            streamService?.stop()
        }
        prevStreamingActive = active
    }

    private fun maybeRefreshPlaylist(version: Int) {
        if (version == lastPlaylistVersion || playlistFetchInFlight) return
        playlistFetchInFlight = true
        viewModelScope.launch {
            val items = PlaylistRepository.fetch(serverIp, serverPort)
            if (items != null) {
                lastPlaylistVersion = version
                _uiState.update { it.copy(playlist = items) }
            }
            playlistFetchInFlight = false
        }
    }

    override fun onCleared() {
        discoveryManager.stop()
        metadataPoller?.stop()
        super.onCleared()
    }
}
