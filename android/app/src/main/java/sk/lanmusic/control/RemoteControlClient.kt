package sk.lanmusic.control

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Sends remote-control commands to the PC player via POST /api/control.
 * Fire-and-forget: the resulting state is observed through the metadata poller.
 */
class RemoteControlClient(private val ip: String, private val port: Int) {

    private suspend fun post(body: JSONObject) = withContext(Dispatchers.IO) {
        runCatching {
            val conn = URL("http://$ip:$port/api/control").openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.connectTimeout = 2000
            conn.readTimeout = 2000
            conn.setRequestProperty("Content-Type", "application/json")
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            conn.responseCode // forces the request to be sent
            conn.disconnect()
        }
    }

    suspend fun playPause() = post(JSONObject().put("action", "playpause"))
    suspend fun stop() = post(JSONObject().put("action", "stop"))
    suspend fun next() = post(JSONObject().put("action", "next"))
    suspend fun prev() = post(JSONObject().put("action", "prev"))
    suspend fun seek(positionMs: Long) =
        post(JSONObject().put("action", "seek").put("positionMs", positionMs))
    suspend fun playIndex(index: Int) =
        post(JSONObject().put("action", "playIndex").put("index", index))
    suspend fun setVolume(value: Int) =
        post(JSONObject().put("action", "setVolume").put("value", value))
    suspend fun shutdown() = post(JSONObject().put("action", "shutdown"))
    suspend fun sleep() = post(JSONObject().put("action", "sleep"))

    /**
     * "Spanok" — PC preskoci na tretiu skladbu od konca playlistu, takze
     * dohraju uz len posledne tri. Kolko ich je, urcuje PC (`_SLEEP_TAIL_TRACKS`),
     * nie telefon.
     *
     * Pocitac tym NEUSPAVA: to spravi az "Vypnut / Spat po skonceni" v appke
     * na PC. Tu je to rovnake ako pri stlaceni tlacidla priamo na pocitaci.
     */
    suspend fun spanok() = post(JSONObject().put("action", "spanok"))

    /**
     * "Spanok 2" — PC prida na koniec playlistu skladby zo svojho zoznamu
     * (spanok2.m3u) a hned ich pusti. Ci sa playlist po dohrati vrati do
     * povodneho stavu, rozhoduje znacka v tom subore na PC, nie telefon.
     */
    suspend fun sleep2() = post(JSONObject().put("action", "sleep2"))
}
