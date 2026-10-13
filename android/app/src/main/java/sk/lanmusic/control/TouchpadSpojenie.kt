package sk.lanmusic.control

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.io.IOException
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket

/** Necinne spojenie sa zavrie — PC ho zavrie az po 180 s, takze telefon
 *  nikdy nepise do spojenia, ktore uz druha strana zahodila. */
private const val NECINNOST_MS = 60_000L
private const val CONNECT_TIMEOUT_MS = 3_000

sealed class TouchpadStav {
    object Necinny : TouchpadStav()
    object Pripojeny : TouchpadStav()
    data class Chyba(val sprava: String) : TouchpadStav()
}

private class StaraVerziaPc : IOException("PC appka touchpad nepozná — aktualizuj ju na PC.")

/**
 * Jedno trvale TCP spojenie na `POST /api/mouse` prehravaca na PC; po nom
 * idu riadky protokolu z `music_player/mys.py` (m / c / d / u / s / h / t / k).
 *
 * Poradie sa drzi (klik nepredbehne posun, ktory ho predchadzal) a nic sa
 * nestrati — preto TCP, nie UDP. Pohyby, ktore sa nahromadia, kym sa pise,
 * idu jednym zapisom.
 */
class TouchpadSpojenie(
    private val ip: String,
    private val port: Int,
    scope: CoroutineScope,
) {
    private val fronta = Channel<String>(Channel.UNLIMITED)
    private val _stav = MutableStateFlow<TouchpadStav>(TouchpadStav.Necinny)
    val stav: StateFlow<TouchpadStav> = _stav

    private val job: Job = scope.launch(Dispatchers.IO) { beh() }

    fun posli(prikaz: String) {
        fronta.trySend(prikaz)
    }

    fun zavri() {
        fronta.close()
        job.cancel()
    }

    private suspend fun beh() {
        var socket: Socket? = null
        var out: OutputStream? = null
        fun odpoj() {
            runCatching { socket?.close() }
            socket = null
            out = null
        }
        try {
            while (currentCoroutineContext().isActive) {
                val prijem = if (socket == null) {
                    fronta.receiveCatching()
                } else {
                    withTimeoutOrNull(NECINNOST_MS) { fronta.receiveCatching() }
                }
                if (prijem != null && prijem.isClosed) break
                val prvy = prijem?.getOrNull()
                if (prvy == null) {       // necinnost
                    odpoj()
                    _stav.value = TouchpadStav.Necinny
                    continue
                }
                val davka = StringBuilder(prvy).append('\n')
                while (true) {
                    val dalsi = fronta.tryReceive().getOrNull() ?: break
                    davka.append(dalsi).append('\n')
                }
                val bajty = davka.toString().toByteArray(Charsets.UTF_8)
                // Dva pokusy: spojenie mohlo medzitym padnut (PC zaspal,
                // prehravac sa restartoval) — vtedy sa hned otvori nove.
                for (pokus in 0..1) {
                    try {
                        if (socket == null) {
                            val s = otvor()
                            socket = s
                            out = s.getOutputStream()
                        }
                        out!!.write(bajty)
                        out!!.flush()
                        _stav.value = TouchpadStav.Pripojeny
                        break
                    } catch (e: StaraVerziaPc) {
                        odpoj()
                        _stav.value = TouchpadStav.Chyba(e.message.orEmpty())
                        break
                    } catch (e: IOException) {
                        odpoj()
                        if (pokus == 1) {
                            _stav.value = TouchpadStav.Chyba("PC neodpovedá ($ip:$port).")
                        }
                    }
                }
            }
        } finally {
            odpoj()
        }
    }

    private fun otvor(): Socket {
        val s = Socket()
        try {
            s.tcpNoDelay = true
            s.connect(InetSocketAddress(ip, port), CONNECT_TIMEOUT_MS)
            s.soTimeout = CONNECT_TIMEOUT_MS
            val out = s.getOutputStream()
            out.write("POST /api/mouse HTTP/1.1\r\nHost: $ip\r\n\r\n".toByteArray())
            out.flush()
            // Odpoved je "HTTP/1.0 200 ...", hlavicky a "ok\n". Starsia verzia
            // prehravaca vrati 404 a spojenie zavrie.
            val vstup = s.getInputStream()
            val prijate = StringBuilder()
            while (!prijate.endsWith("\nok\n") && prijate.length < 2048) {
                val b = vstup.read()
                if (b < 0) break
                prijate.append(b.toChar())
            }
            if (!prijate.startsWith("HTTP/1.0 200") && !prijate.startsWith("HTTP/1.1 200")) {
                throw StaraVerziaPc()
            }
            if (!prijate.endsWith("\nok\n")) throw IOException("neuplna odpoved")
            s.soTimeout = 0
            return s
        } catch (e: Exception) {
            runCatching { s.close() }
            throw if (e is IOException) e else IOException(e)
        }
    }
}
