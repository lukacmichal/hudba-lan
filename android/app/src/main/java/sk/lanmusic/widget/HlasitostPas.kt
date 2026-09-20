package sk.lanmusic.widget

/**
 * Hodnoty pasu hlasitosti vo widgete.
 *
 * Widget nema posuvnik — `RemoteViews` ho nevedia a tahanie by launcher
 * zobral ako prechod na dalsiu stranu plochy. Pas je preto rozdeleny na
 * [DIELIKOV] dielikov a tuknutie na dielik nastavi jeho hodnotu. Pri dvadsiatich
 * je to po 5 %: jemnejsie by uz prst na widgete netrafil, hrubsie by medzi
 * "potichu" a "akurat" nebolo kam tuknut.
 *
 * Dielik nastavi hlasitost na svoj PRAVY okraj — prvy 5, posledny 100. Vypln
 * pasu tak po tuknuti skonci presne tam, kam prst tukol. Nula sa pasom
 * nenastavuje, na to je stlmenie.
 *
 * Oddelene od widgetu kvoli testom — tie bezia na JVM bez Androidu.
 */
object HlasitostPas {

    const val DIELIKOV = 20
    const val MIN = 0
    const val MAX = 100

    /** Hlasitost, na ktoru sa vrati stlmenie, ked widget nevie, co bolo predtym. */
    const val PO_STLMENI = 50

    /** Hlasitost, ktoru nastavi dielik [index] (0 = najlavejsi). */
    fun hodnotaDielika(index: Int): Int =
        ((index.coerceIn(0, DIELIKOV - 1) + 1) * MAX / DIELIKOV)

    /**
     * Stlmenie a jeho zrusenie — to iste, co robi ikonka reproduktora v appke
     * (`PlayerViewModel.onToggleMute`), vratane navratu na [PO_STLMENI], ked
     * hodnota pred stlmenim nie je znama.
     *
     * @param predStlmenim hlasitost pred poslednym stlmenim z widgetu, alebo
     *   hodnota <= 0, ked ziadna nie je.
     */
    fun prepniStlmenie(z: Int, predStlmenim: Int): Int =
        if (z > MIN) MIN
        else if (predStlmenim > MIN) predStlmenim.coerceAtMost(MAX)
        else PO_STLMENI
}
