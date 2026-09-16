package sk.lanmusic.update

import java.io.File

sealed interface UpdateState {
    data object Idle : UpdateState
    data object NotConfigured : UpdateState
    data object Checking : UpdateState
    data object UpToDate : UpdateState

    /**
     * The NAS has a newer build, but nothing has been downloaded yet.
     *
     * This state exists so the ~50 MB APK is only pulled after the user says
     * yes — the same rule every other app follows (docs/shared-standard.md 2.4).
     */
    data class Available(val manifest: UpdateManifest) : UpdateState
    data class Downloading(val progress: Float) : UpdateState
    data class ReadyToInstall(val manifest: UpdateManifest, val file: File) : UpdateState
    data class Failed(val reason: String) : UpdateState
}
