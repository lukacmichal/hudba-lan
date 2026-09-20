package sk.lanmusic.widget

import org.junit.Assert.assertEquals
import org.junit.Test

class HlasitostPasTest {

    @Test
    fun `dielik nastavi svoj pravy okraj`() {
        assertEquals(5, HlasitostPas.hodnotaDielika(0))
        assertEquals(50, HlasitostPas.hodnotaDielika(9))
        assertEquals(100, HlasitostPas.hodnotaDielika(HlasitostPas.DIELIKOV - 1))
    }

    @Test
    fun `dieliky su po piatich a nepreskocia hodnotu`() {
        val hodnoty = (0 until HlasitostPas.DIELIKOV).map { HlasitostPas.hodnotaDielika(it) }
        assertEquals((5..100 step 5).toList(), hodnoty)
    }

    @Test
    fun `index mimo pasu sa oreze`() {
        assertEquals(5, HlasitostPas.hodnotaDielika(-3))
        assertEquals(100, HlasitostPas.hodnotaDielika(99))
    }

    @Test
    fun `stlmenie a navrat na povodnu hlasitost`() {
        assertEquals(0, HlasitostPas.prepniStlmenie(35, predStlmenim = -1))
        assertEquals(35, HlasitostPas.prepniStlmenie(0, predStlmenim = 35))
    }

    @Test
    fun `bez hodnoty pred stlmenim sa vrati na to iste ako v appke`() {
        assertEquals(HlasitostPas.PO_STLMENI, HlasitostPas.prepniStlmenie(0, predStlmenim = -1))
        assertEquals(HlasitostPas.PO_STLMENI, HlasitostPas.prepniStlmenie(0, predStlmenim = 0))
    }
}
