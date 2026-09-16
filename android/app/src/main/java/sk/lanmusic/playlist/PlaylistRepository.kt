package sk.lanmusic.playlist

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import sk.lanmusic.Prenos
import java.net.HttpURLConnection
import java.net.URL

data class PlaylistItem(
    val index: Int,
    val title: String,
    val artist: String,
    val durationMs: Long,
)

/** Fetches the full playlist from GET /api/playlist (only when the version changes). */
object PlaylistRepository {

    suspend fun fetch(ip: String, port: Int): List<PlaylistItem>? = withContext(Dispatchers.IO) {
        runCatching {
            val conn = URL("http://$ip:$port/api/playlist").openConnection() as HttpURLConnection
            conn.connectTimeout = 3000
            conn.readTimeout = 3000
            try {
                if (conn.responseCode != 200) return@runCatching null
                val body = conn.inputStream.bufferedReader().readText()
                // Playlist je najvacsi JSON, aky appka od prehravaca pyta.
                Prenos.nazbieraj(body.toByteArray().size.toLong())
                val items = JSONObject(body).optJSONArray("items")
                    ?: return@runCatching emptyList<PlaylistItem>()
                (0 until items.length()).map { i ->
                    val o = items.getJSONObject(i)
                    PlaylistItem(
                        index = o.optInt("index", i),
                        title = o.optString("title"),
                        artist = o.optString("artist"),
                        durationMs = o.optLong("durationMs", 0L),
                    )
                }
            } finally {
                conn.disconnect()
            }
        }.getOrNull()
    }
}
