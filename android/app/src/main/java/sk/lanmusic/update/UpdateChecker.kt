package sk.lanmusic.update

import sk.lanmusic.Prenos
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import java.security.MessageDigest

/**
 * Decides whether an update is needed and prepares it for install.
 *
 * Deliberately free of Android APIs: the installed version arrives as a
 * lambda and the download target as a plain File, so the whole decision
 * path is unit-testable without a device or a network.
 */
class UpdateChecker(
    private val source: UpdateSource,
    private val cacheDir: File,
    private val currentVersionCode: () -> Long,
) {
    private val _state = MutableStateFlow<UpdateState>(UpdateState.Idle)
    val state: StateFlow<UpdateState> = _state.asStateFlow()

    /**
     * What the NAS last reported, regardless of whether it was newer.
     *
     * The version footer shows this even when we are up to date, so it stays
     * null only when the NAS could not be read at all.
     */
    private val _remote = MutableStateFlow<UpdateManifest?>(null)
    val remote: StateFlow<UpdateManifest?> = _remote.asStateFlow()

    private val updatesDir: File get() = File(cacheDir, "updates")

    /**
     * Reads the manifest only — a few hundred bytes. The APK itself is left
     * alone until [download] is called, which happens after the user confirms.
     */
    suspend fun check(cfg: UpdateConfig) {
        if (!cfg.isComplete) {
            _state.value = UpdateState.NotConfigured
            return
        }
        _state.value = UpdateState.Checking

        val manifest = try {
            source.fetchManifest(cfg)
        } catch (e: Exception) {
            _state.value = UpdateState.Failed(e.friendlyMessage())
            return
        }
        _remote.value = manifest

        // A missing or unreadable manifest is not an error the user can act
        // on — treat it the same as "nothing new".
        if (manifest == null || manifest.versionCode <= currentVersionCode()) {
            _state.value = UpdateState.UpToDate
            return
        }
        _state.value = UpdateState.Available(manifest)
    }

    /** Pulls the APK named by [manifest] and verifies it. Call after a yes. */
    suspend fun download(cfg: UpdateConfig, manifest: UpdateManifest) {
        // Never accumulate old builds in the cache.
        updatesDir.deleteRecursively()
        updatesDir.mkdirs()
        val target = File(updatesDir, manifest.apk)

        _state.value = UpdateState.Downloading(0f)
        try {
            source.downloadApk(cfg, manifest.apk, target) { p ->
                _state.value = UpdateState.Downloading(p.coerceIn(0f, 1f))
            }
        } catch (e: Exception) {
            updatesDir.deleteRecursively()
            _state.value = UpdateState.Failed(e.friendlyMessage())
            return
        }

        if (manifest.sha256.isNotBlank()) {
            val actual = sha256Of(target)
            if (!actual.equals(manifest.sha256, ignoreCase = true)) {
                updatesDir.deleteRecursively()
                _state.value = UpdateState.Failed(
                    "Kontrolný súčet nesedí — súbor je poškodený alebo neúplný."
                )
                return
            }
        }

        // Najvacsi jednorazovy prenos, aky appka spravi.
        Prenos.nazbieraj(target.length())
        _state.value = UpdateState.ReadyToInstall(manifest, target)
    }

    fun reset() {
        _state.value = UpdateState.Idle
    }

    private fun sha256Of(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(8192)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                digest.update(buf, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}

private fun Exception.friendlyMessage(): String =
    message?.takeIf { it.isNotBlank() } ?: (this::class.simpleName ?: "Neznáma chyba")
