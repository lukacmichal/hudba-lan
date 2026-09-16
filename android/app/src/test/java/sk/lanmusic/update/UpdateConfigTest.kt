package sk.lanmusic.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateConfigTest {

    @Test
    fun `defaults point at the NAS share this app ships against`() {
        val c = UpdateConfig()
        assertEquals("nas.local", c.host)
        assertEquals("Android", c.share)
        assertEquals("Player", c.folder)
    }

    @Test
    fun `an explicitly blank username is incomplete`() {
        // Not UpdateConfig(): since the credentials moved into BuildConfig, the
        // default username is whatever the build baked in — on a machine with
        // nas-credentials.local present that is non-blank, so relying on the
        // default here would make the test pass or fail by environment.
        assertFalse(UpdateConfig(username = "").isComplete)
    }

    @Test
    fun `folder is optional so files may sit in the share root`() {
        assertTrue(UpdateConfig(username = "nasuser", folder = "").isComplete)
    }

    @Test
    fun `remote path joins folder and file with a backslash`() {
        assertEquals(
            "Player\\latest.json",
            UpdateConfig(folder = "Player").remotePath("latest.json"),
        )
    }

    @Test
    fun `remote path is the bare name when no folder is set`() {
        assertEquals("latest.json", UpdateConfig(folder = "").remotePath("latest.json"))
    }

    @Test
    fun `remote path tolerates slashes the user typed`() {
        // People paste "Android/Player" or "\Player\" out of Explorer.
        assertEquals("Player\\a.apk", UpdateConfig(folder = "/Player/").remotePath("a.apk"))
        assertEquals("Player\\a.apk", UpdateConfig(folder = "\\Player\\").remotePath("a.apk"))
        assertEquals("sub\\dir\\a.apk", UpdateConfig(folder = "sub/dir").remotePath("a.apk"))
    }

    @Test
    fun `complete once a username is present`() {
        assertTrue(UpdateConfig(username = "nasuser").isComplete)
    }

    @Test
    fun `blank host makes it incomplete`() {
        assertFalse(UpdateConfig(host = "  ", username = "nasuser").isComplete)
    }
}
