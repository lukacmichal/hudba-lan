package sk.lanmusic.widget

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VelkostOvladacaTest {

    @Test
    fun `plna velkost od 128 dp a pri neznamej vyske alebo sirke`() {
        assertEquals(1f, VelkostOvladaca.mierka(128))
        assertEquals(1f, VelkostOvladaca.mierka(260))
        assertEquals(1f, VelkostOvladaca.mierka(0))
        assertEquals(1f, VelkostOvladaca.mierka(128, 362))
    }

    @Test
    fun `medzi 90 a 128 dp sa vsetko zmensi tak, aby sa zmestilo`() {
        for (vyska in 90 until 128) {
            val m = VelkostOvladaca.mierka(vyska)
            assertTrue("$vyska dp", m < 1f)
            assertTrue("$vyska dp", VelkostOvladaca.PLNA_DP * m <= vyska + 0.001f)
        }
        assertEquals(0.703f, VelkostOvladaca.mierka(90), 0.001f)
    }

    @Test
    fun `nad 128 dp sa obsah zvacsi a vzdy sa zmesti`() {
        for (vyska in 129..400) {
            val m = VelkostOvladaca.mierka(vyska, 500)
            assertTrue("$vyska dp", m >= 1f && m <= VelkostOvladaca.NAJVIAC)
            assertTrue("$vyska dp", VelkostOvladaca.PLNA_DP * m <= vyska + 0.001f)
        }
        assertEquals(VelkostOvladaca.NAJVIAC, VelkostOvladaca.mierka(300, 500), 0.001f)
    }

    @Test
    fun `zvacsenie nezuzi nazov skladby pod 110 dp`() {
        // S26 so 4 stlpcami ~362 dp: 362 - 30 - 110 = 222 = 176 dp × 1,26.
        assertEquals(222f / 176f, VelkostOvladaca.mierka(205, 362), 0.001f)
        // Uzky widget sa nezvacsi vobec, no ani nezmensi.
        assertEquals(1f, VelkostOvladaca.mierka(205, 250), 0.001f)
    }

    @Test
    fun `bez hlasitosti sa nezmensuje`() {
        assertEquals(1f, VelkostOvladaca.mierka(89))
        assertEquals(1f, VelkostOvladaca.mierka(40))
    }

    @Test
    fun `hlasitost od 90 dp, na Androide 11 az od 120`() {
        assertFalse(VelkostOvladaca.sHlasitostou(89, zmensuje = true))
        assertTrue(VelkostOvladaca.sHlasitostou(90, zmensuje = true))
        assertFalse(VelkostOvladaca.sHlasitostou(119, zmensuje = false))
        assertTrue(VelkostOvladaca.sHlasitostou(120, zmensuje = false))
        assertTrue(VelkostOvladaca.sHlasitostou(0, zmensuje = true))
        assertTrue(VelkostOvladaca.sHlasitostou(0, zmensuje = false))
    }

    @Test
    fun `podoby pre launcher idu od bez hlasitosti po najvacsie zvacsenie`() {
        val vysky = VelkostOvladaca.VYSKY
        assertEquals(vysky.sorted().distinct(), vysky)
        assertTrue(vysky.size <= 16)
        assertFalse(VelkostOvladaca.sHlasitostou(vysky.first(), zmensuje = true))
        assertTrue(vysky.drop(1).all { VelkostOvladaca.sHlasitostou(it, zmensuje = true) })
        assertEquals(VelkostOvladaca.S_HLASITOSTOU_MIN_DP, vysky[1])
        assertTrue(VelkostOvladaca.PLNA_DP in vysky)
        // Najvyssia podoba je presne najvacsie zvacsenie — vyssia by bola zbytocna.
        assertEquals(VelkostOvladaca.PLNA_DP * VelkostOvladaca.NAJVIAC, vysky.last().toFloat(), 1f)
    }
}
