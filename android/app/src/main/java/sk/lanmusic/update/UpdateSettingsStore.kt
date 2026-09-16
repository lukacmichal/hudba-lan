package sk.lanmusic.update

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import sk.lanmusic.BuildConfig

private const val TAG = "UpdateSettings"
private const val PREFS = "lanmusic_update"
private const val PREFS_SECRET = "lanmusic_secret"
private const val K_PASSWORD = "password"

/**
 * Persists the NAS credentials in app-private storage.
 *
 * SharedPreferences survive app updates, so the user enters this once.
 *
 * The password lives in EncryptedSharedPreferences with the master key held by
 * the Android Keystore; everything else stays in plain prefs. App-private
 * storage alone was the earlier reasoning, but it only holds while the device
 * is unrooted and backups are off — encrypting the one secret costs nothing and
 * removes that dependency. If the Keystore is ever unusable we fall back to
 * plain prefs so the app still runs, same as stocks and homesecure do.
 */
class UpdateSettingsStore(context: Context) {

    private val app = context.applicationContext
    private val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private val secret: SharedPreferences by lazy {
        val store = try {
            val key = MasterKey.Builder(app)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                app, PREFS_SECRET, key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        } catch (e: Exception) {
            Log.w(TAG, "encrypted prefs unavailable, falling back to plain", e)
            app.getSharedPreferences(PREFS_SECRET, Context.MODE_PRIVATE)
        }
        migrateLegacyPassword(store)
        store
    }

    /**
     * Moves a password written by an older build out of the plain store.
     *
     * Without this the user would silently lose the saved password on upgrade.
     * The old copy is removed right after — leaving it behind would defeat the
     * point of encrypting it.
     */
    private fun migrateLegacyPassword(target: SharedPreferences) {
        val legacy = prefs.getString(K_PASSWORD, null) ?: return
        target.edit().putString(K_PASSWORD, legacy).apply()
        prefs.edit().remove(K_PASSWORD).apply()
        Log.i(TAG, "NAS password moved into encrypted prefs")
    }

    /**
     * A blank stored field means "keep the build-time default", not "connect
     * anonymously" — otherwise clearing a field in settings would cut the app
     * off from the NAS for good.
     */
    fun load(): UpdateConfig {
        val defaults = UpdateConfig()
        fun s(key: String, fallback: String) =
            prefs.getString(key, fallback)?.ifBlank { fallback } ?: fallback
        return UpdateConfig(
            host = s("host", defaults.host),
            share = s("share", defaults.share),
            folder = s("folder", defaults.folder),
            username = s("username", defaults.username),
            password = (secret.getString(K_PASSWORD, "") ?: "")
                .ifEmpty { defaults.password },
        )
    }

    fun save(cfg: UpdateConfig) {
        prefs.edit()
            .putString("host", cfg.host.trim())
            .putString("share", cfg.share.trim())
            .putString("folder", cfg.folder.trim())
            .putString("username", cfg.username.trim())
            .apply()
        // A password identical to the one the build baked in is NOT stored:
        // that copy would later shadow a rotated value from the shared
        // credentials file and the app would keep authenticating with the old
        // one. Not trimmed: a space can legitimately be part of a password.
        secret.edit().apply {
            if (cfg.password.isEmpty() || cfg.password == BuildConfig.NAS_PASS) {
                remove(K_PASSWORD)
            } else {
                putString(K_PASSWORD, cfg.password)
            }
        }.apply()
    }
}
