package sk.lanmusic.update

import java.io.File

/**
 * Where updates come from.
 *
 * Kept as an interface so [UpdateChecker] can be tested without a network,
 * and so the SMB library can be swapped without touching the logic.
 */
interface UpdateSource {

    /** Reads and parses latest.json. Throws on any I/O or auth failure. */
    suspend fun fetchManifest(cfg: UpdateConfig): UpdateManifest?

    /** Downloads [name] from the share root into [target]. */
    suspend fun downloadApk(
        cfg: UpdateConfig,
        name: String,
        target: File,
        onProgress: (Float) -> Unit,
    )
}
