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

// Rucne zadana adresa prehravaca. Ma prednost pred vyhladavanim a NEPREPISUJE
// sa nim — kto ju zadal, chce prave ju.
private const val PREF_MANUAL_IP = "manual_ip"
private const val PREF_MANUAL_PORT = "manual_port"
const val DEFAULT_API_PORT = 8765
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

    /**
     * Rucne zadana adresa prehravaca, alebo null ked sa ma hladat samo.
     *
     * Vyhladavanie stoji na UDP beacone, ktory PC vysiela do lokalnej siete —
     * a ten sa nedostane cez Tailscale, cez oddelenu Wi-Fi pre hostí ani cez
     * router, ktory broadcast blokuje. Vtedy je rucna adresa jedina cesta.
     */
    fun manualServer(): Pair<String, Int>? {
        val ip = prefs.getString(PREF_MANUAL_IP, "").orEmpty().trim()
        if (ip.isEmpty()) return null
        return ip to prefs.getInt(PREF_MANUAL_PORT, DEFAULT_API_PORT)
    }

    /** Prazdna adresa = vrat sa k automatickemu vyhladavaniu. */
    fun saveManualServer(ip: String, port: Int) {
        val cisty = ip.trim()
        prefs.edit().apply {
            if (cisty.isEmpty()) {
                remove(PREF_MANUAL_IP)
                remove(PREF_MANUAL_PORT)
            } else {
                putString(PREF_MANUAL_IP, cisty)
                putInt(PREF_MANUAL_PORT, if (port > 0) port else DEFAULT_API_PORT)
            }
        }.apply()
    }

    private suspend fun runDiscovery() {
        _state.value = DiscoveryState.Discovering

        // 0. Rucne zadana adresa vyhrava nad vsetkym ostatnym.
        //
        // Ked neodpoveda, NEPREPADNE sa to na hladanie beaconom: adresa,
        // ktoru clovek zapisal rukou, sa nema ticho obchadzat — inak by sa
        // preklep tvaril ako "server nebezi" a appka by sa medzitym pripojila
        // na uplne iny stroj.
        manualServer()?.let { (ip, port) ->
            _state.value =
                if (checkHealth(ip, port)) DiscoveryState.Found(ip, port)
                else DiscoveryState.NotFound
            return
        }

        // 1. Skús cached IP
        val cachedIp = prefs.getString(PREF_IP, null)
        val cachedPort = prefs.getInt(PREF_PORT, DEFAULT_API_PORT)
        if (cachedIp != null && checkHealth(cachedIp, cachedPort)) {
            _state.value = DiscoveryState.Found(cachedIp, cachedPort)
            return
        }

        // 2. Beacon scan, opakuj každých 5s pokiaľ nenájde
        while (currentCoroutineContext().isActive) {
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
                sock.bind(InetSocketAddress(BEACON_PORT))  // port-only = wildcard 0.0.0.0
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
            val port = json.getInt("apiPort")
            // Prefer the packet's real sender address — the "ip" field can be
            // stale (e.g. 127.0.0.1 when the PC app started before the network).
            val senderIp = packet.address?.hostAddress
            val ip = if (!senderIp.isNullOrBlank() && senderIp != "127.0.0.1") {
                senderIp
            } else {
                json.getString("ip")
            }
            if (ip.isBlank() || ip == "127.0.0.1") return null
            Pair(ip, port)
        } catch (_: JSONException) {
            null
        } catch (_: Exception) {
            null
        }
    }
}
