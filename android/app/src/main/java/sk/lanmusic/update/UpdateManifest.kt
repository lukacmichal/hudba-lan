package sk.lanmusic.update

import org.json.JSONObject

/** Contents of latest.json on the NAS share. */
data class UpdateManifest(
    val versionCode: Long,
    val versionName: String,
    val apk: String,
    val sha256: String,
    val notes: String,
) {
    companion object {
        /** Returns null for anything we cannot trust; callers treat null as "no update". */
        fun parse(text: String): UpdateManifest? = try {
            val o = JSONObject(text)
            val code = o.optLong("versionCode", -1L)
            val apk = o.optString("apk", "")
            when {
                code <= 0L -> null
                apk.isBlank() -> null
                // Keep the manifest confined to the share root.
                apk.contains('/') || apk.contains('\\') -> null
                else -> UpdateManifest(
                    versionCode = code,
                    versionName = o.optString("versionName", ""),
                    apk = apk,
                    sha256 = o.optString("sha256", "").lowercase(),
                    notes = o.optString("notes", ""),
                )
            }
        } catch (e: Exception) {
            null
        }
    }
}
