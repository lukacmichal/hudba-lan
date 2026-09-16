package sk.lanmusic.update

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest

class UpdateCheckerTest {

    @get:Rule val tmp = TemporaryFolder()

    private val cfg = UpdateConfig(username = "nasuser")

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }

    /** Fake source: serves a manifest and fixed APK bytes, no network. */
    private class FakeSource(
        val manifest: UpdateManifest?,
        val apkBytes: ByteArray = ByteArray(0),
        val failManifest: Boolean = false,
        val failDownload: Boolean = false,
    ) : UpdateSource {
        override suspend fun fetchManifest(cfg: UpdateConfig): UpdateManifest? {
            if (failManifest) throw java.io.IOException("nas down")
            return manifest
        }

        override suspend fun downloadApk(
            cfg: UpdateConfig,
            name: String,
            target: File,
            onProgress: (Float) -> Unit,
        ) {
            if (failDownload) throw java.io.IOException("interrupted")
            target.parentFile?.mkdirs()
            target.writeBytes(apkBytes)
            onProgress(1f)
        }
    }

    private fun manifest(code: Long, sha: String = "") =
        UpdateManifest(code, "9.9", "lanmusic-9.9.apk", sha, "")

    private fun checker(source: UpdateSource, installed: Long = 4L) =
        UpdateChecker(
            source = source,
            cacheDir = tmp.root,
            currentVersionCode = { installed },
        )

    /**
     * Checking and downloading are two steps: the ~50 MB APK is only pulled
     * after the user confirms. This helper walks both, the way the ViewModel
     * does once the dialog is accepted.
     */
    private suspend fun UpdateChecker.checkAndDownload(cfg: UpdateConfig) {
        check(cfg)
        (state.value as? UpdateState.Available)?.let { download(cfg, it.manifest) }
    }

    @Test
    fun `newer version is offered without downloading anything`() = runTest {
        val apk = "fake apk".toByteArray()
        val c = checker(FakeSource(manifest(5, sha256(apk)), apk))

        c.check(cfg)

        val state = c.state.value
        assertTrue("was $state", state is UpdateState.Available)
        assertEquals(5L, (state as UpdateState.Available).manifest.versionCode)
        // The point of the state: nothing has been pulled over the network yet.
        assertEquals(0, File(tmp.root, "updates").listFiles().orEmpty().size)
    }

    @Test
    fun `confirmed update downloads and becomes ready to install`() = runTest {
        val apk = "fake apk".toByteArray()
        val c = checker(FakeSource(manifest(5, sha256(apk)), apk))

        c.checkAndDownload(cfg)

        val state = c.state.value
        assertTrue("was $state", state is UpdateState.ReadyToInstall)
        val ready = state as UpdateState.ReadyToInstall
        assertEquals(5L, ready.manifest.versionCode)
        assertTrue(ready.file.exists())
        assertEquals("fake apk", ready.file.readText())
    }

    @Test
    fun `remote version is remembered even when up to date`() = runTest {
        // The footer shows what lies on the NAS regardless of whether it is
        // newer, so `remote` must be filled on a no-op check too.
        val c = checker(FakeSource(manifest(4)))
        c.check(cfg)
        assertEquals(4L, c.remote.value?.versionCode)
    }

    @Test
    fun `same version code is up to date`() = runTest {
        val c = checker(FakeSource(manifest(4)))
        c.check(cfg)
        assertEquals(UpdateState.UpToDate, c.state.value)
    }

    @Test
    fun `older version code is up to date`() = runTest {
        val c = checker(FakeSource(manifest(3)))
        c.check(cfg)
        assertEquals(UpdateState.UpToDate, c.state.value)
    }

    @Test
    fun `incomplete config short-circuits without touching the source`() = runTest {
        val c = checker(FakeSource(manifest(9)))
        // Blank username spelled out rather than left to the default: the
        // default now carries whatever the build read from nas-credentials.local.
        c.check(UpdateConfig(username = ""))
        assertEquals(UpdateState.NotConfigured, c.state.value)
    }

    @Test
    fun `unreachable nas fails without crashing`() = runTest {
        val c = checker(FakeSource(null, failManifest = true))
        c.check(cfg)
        assertTrue(c.state.value is UpdateState.Failed)
    }

    @Test
    fun `unparseable manifest is treated as up to date`() = runTest {
        val c = checker(FakeSource(null))
        c.check(cfg)
        assertEquals(UpdateState.UpToDate, c.state.value)
    }

    @Test
    fun `checksum mismatch deletes the file and fails`() = runTest {
        val apk = "fake apk".toByteArray()
        val c = checker(FakeSource(manifest(5, sha256("different".toByteArray())), apk))

        c.checkAndDownload(cfg)

        assertTrue(c.state.value is UpdateState.Failed)
        val leftovers = File(tmp.root, "updates").listFiles().orEmpty()
        assertEquals("downloaded file must not survive", 0, leftovers.size)
    }

    @Test
    fun `empty sha256 skips verification`() = runTest {
        val apk = "fake apk".toByteArray()
        val c = checker(FakeSource(manifest(5, ""), apk))
        c.checkAndDownload(cfg)
        assertTrue(c.state.value is UpdateState.ReadyToInstall)
    }

    @Test
    fun `failed download leaves no file behind`() = runTest {
        val c = checker(FakeSource(manifest(5, "aa"), failDownload = true))
        c.checkAndDownload(cfg)
        assertTrue(c.state.value is UpdateState.Failed)
        val leftovers = File(tmp.root, "updates").listFiles().orEmpty()
        assertEquals(0, leftovers.size)
    }

    @Test
    fun `stale downloads are cleared before a new one`() = runTest {
        val updates = File(tmp.root, "updates").apply { mkdirs() }
        val stale = File(updates, "old-1.0.apk").apply { writeText("old") }

        val apk = "new apk".toByteArray()
        checker(FakeSource(manifest(5, sha256(apk)), apk)).checkAndDownload(cfg)

        assertTrue("stale build should be gone", !stale.exists())
    }
}
