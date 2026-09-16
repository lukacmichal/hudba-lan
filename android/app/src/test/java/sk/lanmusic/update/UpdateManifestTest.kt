package sk.lanmusic.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UpdateManifestTest {

    @Test
    fun `parses a valid manifest`() {
        val json = """
            {"versionCode": 4, "versionName": "1.3", "apk": "lanmusic-1.3.apk",
             "sha256": "ABC123", "notes": "nieco"}
        """.trimIndent()

        val m = UpdateManifest.parse(json)!!

        assertEquals(4L, m.versionCode)
        assertEquals("1.3", m.versionName)
        assertEquals("lanmusic-1.3.apk", m.apk)
        assertEquals("abc123", m.sha256)   // normalised to lowercase
        assertEquals("nieco", m.notes)
    }

    @Test
    fun `notes and sha256 are optional`() {
        val m = UpdateManifest.parse("""{"versionCode":4,"versionName":"1.3","apk":"a.apk"}""")!!
        assertEquals("", m.sha256)
        assertEquals("", m.notes)
    }

    @Test
    fun `returns null on malformed json`() {
        assertNull(UpdateManifest.parse("this is not json"))
    }

    @Test
    fun `returns null when versionCode is missing`() {
        assertNull(UpdateManifest.parse("""{"versionName":"1.3","apk":"a.apk"}"""))
    }

    @Test
    fun `returns null when versionCode is not a number`() {
        assertNull(UpdateManifest.parse("""{"versionCode":"x","versionName":"1.3","apk":"a.apk"}"""))
    }

    @Test
    fun `returns null when apk name is blank`() {
        assertNull(UpdateManifest.parse("""{"versionCode":4,"versionName":"1.3","apk":""}"""))
    }

    @Test
    fun `rejects apk names containing a path separator`() {
        // A manifest must not be able to point outside the share directory.
        assertNull(UpdateManifest.parse("""{"versionCode":4,"versionName":"1.3","apk":"../x.apk"}"""))
        assertNull(UpdateManifest.parse("""{"versionCode":4,"versionName":"1.3","apk":"sub/x.apk"}"""))
    }
}
