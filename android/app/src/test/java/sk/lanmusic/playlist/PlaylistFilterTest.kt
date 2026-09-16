package sk.lanmusic.playlist

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaylistFilterTest {

    private val playlist = listOf(
        PlaylistItem(0, "Blackwater Park", "Opeth", 600_000),
        PlaylistItem(1, "Tähtiportti", "Mörk Gryning", 300_000),
        PlaylistItem(2, "Heartwork", "Carcass", 250_000),
        PlaylistItem(3, "Blackwater", "Iná kapela", 200_000),
    )

    private fun titles(q: String) = PlaylistFilter.filter(playlist, q).map { it.title }

    @Test
    fun `prazdny dopyt vrati ten isty zoznam`() {
        // Nie kópiu: playlist má tisíce položiek a kopíroval by sa pri každom
        // prekreslení obrazovky.
        assertSame(playlist, PlaylistFilter.filter(playlist, ""))
        assertSame(playlist, PlaylistFilter.filter(playlist, "   "))
    }

    @Test
    fun `hlada sa v nazve aj v interpretovi`() {
        assertEquals(listOf("Heartwork"), titles("carcass"))
        assertEquals(listOf("Heartwork"), titles("heartwork"))
    }

    @Test
    fun `velkost pismen nerozhoduje`() {
        assertEquals(titles("OPETH"), titles("opeth"))
    }

    @Test
    fun `diakritika nerozhoduje v dopyte ani v nazve`() {
        // "Tähtiportti" od "Mörk Gryning" sa na telefóne nedá napísať presne.
        assertEquals(listOf("Tähtiportti"), titles("tahtiportti"))
        assertEquals(listOf("Tähtiportti"), titles("mork"))
        assertEquals(listOf("Tähtiportti"), titles("Mörk"))
    }

    @Test
    fun `slova sa hladaju samostatne a poradie nerozhoduje`() {
        assertEquals(listOf("Blackwater Park"), titles("opeth blackwater"))
        assertEquals(listOf("Blackwater Park"), titles("blackwater opeth"))
    }

    @Test
    fun `viac zhod vrati vsetky v povodnom poradi`() {
        assertEquals(listOf("Blackwater Park", "Blackwater"), titles("blackwater"))
    }

    @Test
    fun `bez zhody je vysledok prazdny`() {
        assertTrue(titles("nirvana").isEmpty())
    }

    @Test
    fun `index ostava serverovy`() {
        // Podľa neho sa spúšťa prehrávanie — filtrovanie ho nesmie prečíslovať.
        assertEquals(listOf(0, 3), PlaylistFilter.filter(playlist, "blackwater").map { it.index })
    }

    @Test
    fun `normalizacia odstrani diakritiku a zmensi pismena`() {
        assertEquals("mork gryning", PlaylistFilter.normalize("Mörk Gryning"))
        assertEquals("tahle", PlaylistFilter.normalize("Táhle"))
    }

    @Test
    fun `matches na jednej polozke`() {
        assertTrue(PlaylistFilter.matches(playlist[0], "opeth"))
        assertFalse(PlaylistFilter.matches(playlist[0], "carcass"))
    }
}
