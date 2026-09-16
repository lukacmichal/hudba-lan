package sk.lanmusic.metadata

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject
import sk.lanmusic.Prenos
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

    private fun fetchNowPlaying(): NowPlayingState? = nacitaj(ip, port)

    companion object {
        /**
         * Jedno stiahnutie `/api/now-playing`, bez pollera.
         *
         * Vytiahnute z instancie kvoli widgetu (29. 8. 2026): ten po stlaceni
         * tlacidla potrebuje zistit, co na pocitaci prave hra, a vlastny poller
         * by si na to spustat nemohol — bezi len par sekund v receiveri.
         * Kopirovat parsovanie do widgetu by znamenalo dve miesta, ktore sa
         * pri kazdom novom poli rozidu.
         */
        fun nacitaj(ip: String, port: Int): NowPlayingState? {
            return try {
                val conn = URL("http://$ip:$port/api/now-playing")
                    .openConnection() as HttpURLConnection
                conn.connectTimeout = REQUEST_TIMEOUT_MS
                conn.readTimeout = REQUEST_TIMEOUT_MS
                if (conn.responseCode != 200) {
                    conn.disconnect()
                    return null
                }
                val body = conn.inputStream.bufferedReader().readText()
                conn.disconnect()
                // Do pocitadla dat. Nazbiera sa a odovzda az ten, kto ma
                // Context — a to je tu dolezitejsie nez inde: stav sa tiahne
                // kazdu sekundu a kazdy dopyt zvlast by z poctu prenosov
                // spravil cislo bez informacie.
                Prenos.nazbieraj(body.toByteArray().size.toLong())
                val json = JSONObject(body)
                NowPlayingState(
                    title = json.optString("title"),
                    artist = json.optString("artist"),
                    state = json.optString("state", "stopped"),
                    streamingActive = json.optBoolean("streamingActive", false),
                    streamUrl = json.optString("streamUrl"),
                    positionMs = json.optLong("positionMs", 0L),
                    durationMs = json.optLong("durationMs", 0L),
                    currentIndex = json.optInt("currentIndex", -1),
                    playlistVersion = json.optInt("playlistVersion", 0),
                    volume = json.optInt("volume", 50),
                )
            } catch (_: Exception) {
                null
            }
        }
    }
}
