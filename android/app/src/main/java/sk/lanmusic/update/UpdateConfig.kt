package sk.lanmusic.update

import sk.lanmusic.BuildConfig

/**
 * NAS connection settings.
 *
 * Defaults are baked in at build time from the shared
 * `nas-credentials.local`, so a fresh install is already configured.
 *
 * That used to be avoided on the grounds that a changed NAS password would kill
 * self-update and could only be fixed by sideloading. It no longer can: the
 * settings screen still overrides these values and that override wins, so a
 * password change is fixed on the phone. Rotating it in the shared file and
 * rebuilding fixes every app at once.
 */
data class UpdateConfig(
    val host: String = BuildConfig.NAS_HOST.ifBlank { "nas.local" },
    val share: String = BuildConfig.NAS_SHARE.ifBlank { "Android" },
    /** Sub-directory inside the share. Blank means the share root. */
    val folder: String = "Player",
    val username: String = BuildConfig.NAS_USER,
    val password: String = BuildConfig.NAS_PASS,
) {
    /**
     * A blank password is legitimate (guest access) and a blank folder just
     * means the share root, so neither is required here.
     */
    val isComplete: Boolean
        get() = host.isNotBlank() && share.isNotBlank() && username.isNotBlank()

    /**
     * Path of [name] inside the share, as SMB expects it.
     *
     * Tolerates the slashes people paste out of Explorer: leading, trailing
     * and forward slashes are all normalised away.
     */
    fun remotePath(name: String): String {
        val clean = folder.replace('/', '\\').trim('\\', ' ')
        return if (clean.isEmpty()) name else "$clean\\$name"
    }
}
