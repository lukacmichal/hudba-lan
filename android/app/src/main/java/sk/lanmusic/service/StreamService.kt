package sk.lanmusic.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Binder
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.media.app.NotificationCompat.MediaStyle
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import android.util.Log
import org.videolan.libvlc.LibVLC
import org.videolan.libvlc.Media
import org.videolan.libvlc.MediaPlayer
import sk.lanmusic.MainActivity
import sk.lanmusic.Prenos
import sk.lanmusic.R
import sk.lanmusic.control.RemoteControlClient

private const val TAG = "StreamService"

private const val CHANNEL_ID = "lan_music_channel"
private const val NOTIFICATION_ID = 1
const val ACTION_EXIT = "sk.lanmusic.ACTION_EXIT"

// PC transport driven from the pre-Android-13 notification buttons; on 13+
// the system media controls are built from the MediaSession instead.
private const val ACTION_REMOTE_PREV = "sk.lanmusic.ACTION_REMOTE_PREV"
private const val ACTION_REMOTE_PLAYPAUSE = "sk.lanmusic.ACTION_REMOTE_PLAYPAUSE"
private const val ACTION_REMOTE_STOP = "sk.lanmusic.ACTION_REMOTE_STOP"
private const val ACTION_REMOTE_NEXT = "sk.lanmusic.ACTION_REMOTE_NEXT"

// MediaSession custom actions — on Android 13+ the system media controls are
// built from PlaybackState actions, notification addAction() is ignored there.
private const val CUSTOM_ACTION_STOP = "sk.lanmusic.CUSTOM_STOP"
private const val CUSTOM_ACTION_EXIT = "sk.lanmusic.CUSTOM_EXIT"

class StreamService : Service() {

    inner class LocalBinder : Binder() {
        fun getService(): StreamService = this@StreamService
    }

    private val binder = LocalBinder()
    private lateinit var libVlc: LibVLC
    private lateinit var mediaPlayer: MediaPlayer
    private lateinit var mediaSession: MediaSessionCompat
    private lateinit var reconnectHandler: Handler
    private var multicastLock: WifiManager.MulticastLock? = null

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var remoteClient: RemoteControlClient? = null

    // Set while shutting down via "Ukončiť" — blocks every late callback
    // (async LibVLC events, metadata pushes arriving over a stale binder)
    // from re-posting the notification after stopForeground() removed it.
    // Without this the miniature keeps flapping back forever.
    @Volatile
    private var isExiting = false

    private val _playbackState = MutableStateFlow<PlaybackState>(PlaybackState.Stopped)
    val playbackState: StateFlow<PlaybackState> = _playbackState

    private var currentTitle = ""
    private var currentArtist = ""
    private var currentStreamUrl = ""

    // Mirror of the PC player — drives the lock-screen seekbar and buttons.
    private var serverPlaying = false
    private var serverPositionMs = 0L
    private var serverDurationMs = 0L

    override fun onCreate() {
        super.onCreate()
        reconnectHandler = Handler(mainLooper)
        createNotificationChannel()
        acquireMulticastLock()
        initLibVlc()
        initMediaSession()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_EXIT) {
            exit()
            return START_NOT_STICKY
        }
        // A fresh start command after exit() means the user opened the app
        // again while this instance was still alive (the activity's binding
        // keeps it around) — bring it back instead of staying half-dead.
        if (isExiting) revive()
        startForeground(NOTIFICATION_ID, buildNotification())
        when (intent?.action) {
            ACTION_REMOTE_PREV -> sendRemote { it.prev() }
            ACTION_REMOTE_PLAYPAUSE -> sendRemote { it.playPause() }
            ACTION_REMOTE_STOP -> sendRemote { it.stop() }
            ACTION_REMOTE_NEXT -> sendRemote { it.next() }
        }
        // Not sticky: a zombie restart with a null intent would only resurrect
        // the notification after the user exited; the activity restarts the
        // service whenever it is actually needed.
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent): IBinder = binder

    override fun onDestroy() {
        isExiting = true
        prudHandler.removeCallbacks(prudTiknutie)
        zapocitajPrud()
        Prenos.odovzdaj(this)
        reconnectHandler.removeCallbacksAndMessages(null)
        serviceScope.cancel()
        mediaPlayer.setEventListener(null)
        mediaPlayer.stop()
        mediaPlayer.release()
        libVlc.release()
        mediaSession.release()
        multicastLock?.release()
        super.onDestroy()
    }

    /** Point the media-session controls at the PC player's control API. */
    fun configureRemote(ip: String, port: Int) {
        remoteClient = RemoteControlClient(ip, port)
    }

    // ------------------------- pocitadlo dat --------------------------------
    //
    // Prud hudby je NAJVACSI prenos tejto appky — vsetko ostatne (stav
    // prehravaca, playlist) su kilobajty, hodina hudby su desiatky megabajtov.
    // Bez neho by pocitadlo v Nastaveniach tvrdilo, ze appka takmer nic
    // neprenasa, a to je horsie nez ziadne cislo.
    //
    // Bajty hovori LibVLC (`stats.readBytes`), takze sa nic neodhaduje.
    // Cita sa priebezne (kazdych 30 s) a nie az na konci: prehravanie casto
    // skonci tym, ze system sluzbu zabije, a vtedy by sa cele sedenie
    // stratilo. Zapisuje sa cez `nazbieraj`, takze hodina hudby je v pocte
    // JEDEN prenos, nie stodvadsat.
    private var prudOdpisaneBajty = 0L
    private val prudTiknutie = object : Runnable {
        override fun run() {
            zapocitajPrud()
            prudHandler.postDelayed(this, 30_000L)
        }
    }
    private val prudHandler by lazy { Handler(mainLooper) }

    private fun zapocitajPrud() {
        val precitane = runCatching {
            mediaPlayer.media?.stats?.readBytes?.toLong() ?: 0L
        }.getOrDefault(0L)
        val rozdiel = precitane - prudOdpisaneBajty
        if (rozdiel > 0) {
            Prenos.nazbieraj(rozdiel)
            prudOdpisaneBajty = precitane
        }
    }

    fun play(url: String) {
        if (url.isEmpty()) {
            Log.w(TAG, "play() called with empty URL — ignoring")
            return
        }
        // Starting playback again = the user changed their mind after exit.
        if (isExiting) revive()
        Log.d(TAG, "play() url=$url")
        currentStreamUrl = url
        // Az TERAZ vznika notifikacia a aktivne media sedenie — teda ovladanie
        // na zamknutej obrazovke. Zapnutim appky sa to uz nedeje (27. 8. 2026).
        // `startForegroundService` zaroven robi zo sluzby SPUSTENU, nie len
        // zviazanu: bez toho by ju system zrusil, len co clovek appku
        // minimalizuje a aktivita sa odviaze — teda prave vtedy, ked ma hudba
        // hrat dalej.
        androidx.core.content.ContextCompat.startForegroundService(
            this, Intent(this, StreamService::class.java)
        )
        mediaSession.isActive = true
        _playbackState.value = PlaybackState.Connecting
        pushSessionState()
        updateNotificationAndPost()
        // Doterajsi prud sa zarata este starymi statistikami; nove medium
        // zacina citat od nuly, takze aj odpocet musi.
        zapocitajPrud()
        prudOdpisaneBajty = 0L
        val media = Media(libVlc, Uri.parse(url))
        mediaPlayer.media = media
        media.release()
        mediaPlayer.play()
        prudHandler.removeCallbacks(prudTiknutie)
        prudHandler.postDelayed(prudTiknutie, 30_000L)
    }

    /**
     * Zastavi prijem streamu a UPRACE po sebe.
     *
     * Sedenie sa deaktivuje a notifikacia sa odstranuje — nie preto, aby sa
     * setrilo miesto, ale preto, ze prave sedenie kresli ovladanie na
     * zamknutej obrazovke. Nechat ho zapnute po zastaveni by znamenalo to iste,
     * na co sa clovek stazoval: prehravac na zamknutej obrazovke, hoci sa nic
     * neprehrava.
     *
     * Sluzba zostava nazive (aktivita ju drzi zviazanu), takze appka dalej
     * ovlada PC — len o sebe mimo appky nedava vediet.
     */
    fun stop() {
        if (isExiting) return
        mediaPlayer.stop()
        _playbackState.value = PlaybackState.Stopped
        mediaSession.isActive = false
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
    }

    fun updateNowPlaying(
        title: String,
        artist: String,
        positionMs: Long,
        durationMs: Long,
        isServerPlaying: Boolean,
        streamUrl: String,
    ) {
        if (isExiting) return
        currentTitle = title
        currentArtist = artist
        serverPositionMs = positionMs
        serverDurationMs = durationMs
        serverPlaying = isServerPlaying
        if (streamUrl.isNotEmpty()) currentStreamUrl = streamUrl
        mediaSession.setMetadata(
            MediaMetadataCompat.Builder()
                .putString(MediaMetadataCompat.METADATA_KEY_TITLE, title)
                .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, artist)
                .putLong(
                    MediaMetadataCompat.METADATA_KEY_DURATION,
                    if (durationMs > 0) durationMs else -1L,
                )
                .build()
        )
        pushSessionState()
        updateNotificationAndPost()
    }

    private fun exit() {
        if (isExiting) return
        isExiting = true
        reconnectHandler.removeCallbacksAndMessages(null)
        runCatching { mediaPlayer.stop() }
        _playbackState.value = PlaybackState.Stopped
        mediaSession.setActive(false)
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        // Belt and braces: a late notify() may already have re-posted the
        // notification between the last update and the exit tap.
        getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
        stopSelf()
    }

    /** Undo exit() for this still-alive instance (kept around by the
     *  activity's binding) when the user starts using it again. */
    private fun revive() {
        isExiting = false
        // Sedenie sa zapina az v `play()` — tu by ovladanie na zamknutej
        // obrazovke ozilo aj bez prehravania.
        pushSessionState()
    }

    private fun sendRemote(block: suspend (RemoteControlClient) -> Unit) {
        val client = remoteClient ?: return
        serviceScope.launch { block(client) }
    }

    private fun initLibVlc() {
        val options = arrayListOf(
            "--network-caching=1000",
            "--no-video",
            "--aout=opensles",
        )
        libVlc = LibVLC(this, options)
        mediaPlayer = MediaPlayer(libVlc)
        mediaPlayer.setEventListener { event ->
            when (event.type) {
                MediaPlayer.Event.Opening -> {
                    Log.d(TAG, "LibVLC: Opening")
                    _playbackState.value = PlaybackState.Connecting
                    updateNotificationAndPost()
                }
                MediaPlayer.Event.Playing -> {
                    Log.d(TAG, "LibVLC: Playing")
                    _playbackState.value = PlaybackState.Playing
                    updateNotificationAndPost()
                }
                MediaPlayer.Event.Stopped -> {
                    Log.d(TAG, "LibVLC: Stopped")
                    // Koniec sedenia: dorataj zvysok a odovzdaj ho do
                    // pocitadla, kym este vieme, cez aku siet to islo.
                    prudHandler.removeCallbacks(prudTiknutie)
                    zapocitajPrud()
                    Prenos.odovzdaj(this@StreamService)
                    _playbackState.value = PlaybackState.Stopped
                    updateNotificationAndPost()
                }
                MediaPlayer.Event.EndReached -> {
                    // HTTP stream ended = server started a new song; reconnect
                    Log.d(TAG, "LibVLC: EndReached — reconnecting")
                    _playbackState.value = PlaybackState.Connecting
                    updateNotificationAndPost()
                    val url = currentStreamUrl
                    if (!isExiting && url.isNotEmpty()) {
                        reconnectHandler.postDelayed({
                            if (!isExiting) play(url)
                        }, 800)
                    }
                }
                MediaPlayer.Event.EncounteredError -> {
                    Log.e(TAG, "LibVLC: EncounteredError")
                    _playbackState.value = PlaybackState.Error
                    updateNotificationAndPost()
                }
            }
        }
    }

    private fun initMediaSession() {
        mediaSession = MediaSessionCompat(this, "LanMusicSession")
        mediaSession.setCallback(object : MediaSessionCompat.Callback() {
            // Lock-screen / headset controls drive the PC player, not the
            // local stream receiver — the phone is primarily a remote.
            override fun onPlay() = sendRemote { it.playPause() }
            override fun onPause() = sendRemote { it.playPause() }
            override fun onSkipToNext() = sendRemote { it.next() }
            override fun onSkipToPrevious() = sendRemote { it.prev() }
            override fun onStop() = sendRemote { it.stop() }
            override fun onSeekTo(pos: Long) {
                // Optimistic so the bar doesn't snap back before the next poll.
                serverPositionMs = pos
                pushSessionState()
                sendRemote { it.seek(pos) }
            }
            override fun onCustomAction(action: String?, extras: Bundle?) {
                when (action) {
                    CUSTOM_ACTION_STOP -> sendRemote { it.stop() }
                    CUSTOM_ACTION_EXIT -> exit()
                }
            }
        })
        // ZAMERNE sa tu neaktivuje. Aktivne media sedenie samo o sebe vykresli
        // prehravac na zamknutej obrazovke a v rolete — aj keby notifikacia
        // nebola ziadna. Zapina sa az v `play()`.
    }

    private fun pushSessionState() {
        if (isExiting || !mediaSession.isActive) return
        val stateVal = when {
            serverPlaying -> PlaybackStateCompat.STATE_PLAYING
            serverDurationMs > 0 -> PlaybackStateCompat.STATE_PAUSED
            else -> PlaybackStateCompat.STATE_STOPPED
        }
        val speed = if (serverPlaying) 1f else 0f
        mediaSession.setPlaybackState(
            PlaybackStateCompat.Builder()
                .setActions(
                    PlaybackStateCompat.ACTION_PLAY
                        or PlaybackStateCompat.ACTION_PAUSE
                        or PlaybackStateCompat.ACTION_PLAY_PAUSE
                        or PlaybackStateCompat.ACTION_SKIP_TO_NEXT
                        or PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS
                        or PlaybackStateCompat.ACTION_SEEK_TO
                        or PlaybackStateCompat.ACTION_STOP
                )
                // Same controls as in the app: ⏹ Zastaviť + ✕ Ukončiť fill the
                // two free slots next to prev/play/next on the lock screen.
                .addCustomAction(
                    PlaybackStateCompat.CustomAction.Builder(
                        CUSTOM_ACTION_STOP, "Zastaviť", R.drawable.ic_stop
                    ).build()
                )
                .addCustomAction(
                    PlaybackStateCompat.CustomAction.Builder(
                        CUSTOM_ACTION_EXIT, "Ukončiť", R.drawable.ic_close
                    ).build()
                )
                .setState(stateVal, serverPositionMs, speed)
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
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE
        )

        fun serviceAction(requestCode: Int, action: String): PendingIntent =
            PendingIntent.getService(
                this, requestCode,
                Intent(this, StreamService::class.java).also { it.action = action },
                PendingIntent.FLAG_IMMUTABLE
            )

        // Same controls as in the app (⏮ ▶/⏸ ⏹ ⏭ + Ukončiť), all driving the
        // PC player. Android 13+ ignores addAction() for MediaStyle and shows
        // the MediaSession-based controls instead; these cover Android ≤ 12.
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_music)
            .setContentTitle(currentTitle.ifEmpty { "LAN Music" })
            .setContentText(currentArtist)
            .setContentIntent(openIntent)
            .addAction(R.drawable.ic_prev, "Predchádzajúca", serviceAction(10, ACTION_REMOTE_PREV))
            .addAction(
                if (serverPlaying) R.drawable.ic_pause else R.drawable.ic_play,
                if (serverPlaying) "Pauza" else "Prehrať",
                serviceAction(11, ACTION_REMOTE_PLAYPAUSE)
            )
            .addAction(R.drawable.ic_stop, "Zastaviť", serviceAction(12, ACTION_REMOTE_STOP))
            .addAction(R.drawable.ic_next, "Nasledujúca", serviceAction(13, ACTION_REMOTE_NEXT))
            .addAction(R.drawable.ic_close, "Ukončiť", serviceAction(14, ACTION_EXIT))
            .setStyle(
                MediaStyle()
                    .setMediaSession(mediaSession.sessionToken)
                    .setShowActionsInCompactView(0, 1, 3)
            )
            .setOngoing(_playbackState.value is PlaybackState.Playing)
            .build()
    }

    /**
     * Prekresli notifikaciu — ale len ked nejaka ma byt.
     *
     * `updateNowPlaying` chodi z pollovania metadat kazdych par sekund, aj ked
     * sa do telefonu nic nestreamuje. Bez tejto poistky by prve pollnutie po
     * `stop()` notifikaciu (a s nou ovladanie) hned vratilo spat.
     */
    private fun updateNotificationAndPost() {
        if (isExiting || !mediaSession.isActive) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification())
    }
}
