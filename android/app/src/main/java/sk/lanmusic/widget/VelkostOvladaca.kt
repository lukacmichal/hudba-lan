package sk.lanmusic.widget

/**
 * Ako velky ma byt obsah widgetu pri danej vyske (dp).
 *
 * **Preco (26. 10. 2026).** Na S26 Ultra chybal riadok hlasitosti na widgete
 * vysokom jednu aj dve bunky, kym na A52 bol cely. Dve veci:
 *
 * 1. Vyska sa brala z `OPTION_APPWIDGET_MIN_HEIGHT`. Podla dokumentacie je to
 *    vyska widgetu na ploche otocenej NA SIRKU, kde su bunky nizke — na S26
 *    tak zrejme vychadzala pod 120 dp aj pri dvoch bunkach (na telefone to
 *    overene nie je, cisla od launchera nemame).
 * 2. Jedna bunka na S26 je nizsia nez na A52 a plna velkost ([PLNA_DP]) sa do
 *    nej nezmesti. Riadok sa skryl, hoci zmenseny by sa zmestil.
 *
 * Od Androidu 12 preto widget posiela launcheru niekolko podob naraz
 * ([VYSKY]) a launcher si sam vyberie najvacsiu, ktora sa zmesti do
 * skutocnej vysky — na vysku aj na sirku, bez hadania z cisel. Medzi
 * [S_HLASITOSTOU_MIN_DP] a [PLNA_DP] su vsetky tri riadky rovnomerne
 * zmensene ([mierka]), pod tym sa hlasitost skryje ako doteraz.
 *
 * **A naopak (26. 10. 2026, 2.14).** Nad [PLNA_DP] ostaval obsah pevny
 * a prazdno sa nahromadilo okolo tlacidiel prehravania — na S26 maju dve
 * bunky viac dp nez na A52. Teraz sa vsetko zvacsi az na [NAJVIAC], no len
 * tak, aby nazvu skladby v hornom riadku ostalo aspon [NAZOV_MIN_DP] ([naSirku]).
 *
 * Oddelene od widgetu kvoli testom — tie bezia na JVM bez Androidu.
 */
object VelkostOvladaca {

    /** Tri riadky v plnej velkosti: odsadenie 16 + 32 + 4 + 40 + 4 + 32. */
    const val PLNA_DP = 128

    /**
     * Najnizsia vyska, pri ktorej sa este ukaze aj hlasitost — vtedy je
     * vsetko zmensene na 70 %. Menej uz tlacidla hornej rady nie su na prst.
     */
    const val S_HLASITOSTOU_MIN_DP = 90

    /**
     * Android 11 a starsi podoby podla velkosti nepozna a zmensovat nevie
     * (`RemoteViews.setViewLayoutHeight` je az od 12). Tam ostava povodne
     * pravidlo: pod touto vyskou bez hlasitosti, inak plna velkost.
     */
    const val S_HLASITOSTOU_BEZ_ZMENSOVANIA_DP = 120

    /** Najvacsie zvacsenie nad plnu velkost — tlacidla prehravania maju vtedy 64 dp. */
    const val NAJVIAC = 1.6f

    /**
     * Horny riadok z widget_ovladac.xml: pat tlacidiel po 32 dp a okraje
     * widgetu 2 × 8 dp sa zvacsuju, medzery medzi tlacidlami (12 + 3 × 4 dp)
     * a odsadenie nazvu (6 dp) nie.
     */
    private const val HORE_ROSTIE_DP = 5 * 32 + 2 * 8
    private const val HORE_PEVNE_DP = 12 + 3 * 4 + 6

    /** Tolko musi ostat nazvu skladby, aby sa z neho dalo nieco precitat. */
    const val NAZOV_MIN_DP = 110

    /**
     * Podoby widgetu pre Android 12+. Najnizsia je bez hlasitosti, ostatne
     * po 10 dp az po plnu velkost a nad nou po ~15 dp az po [NAJVIAC] —
     * launcher berie najvacsiu, ktora sa zmesti, takze widget nikdy nie je
     * mensi o viac nez jeden krok zbytocne. Launcher ich prijme najviac 16.
     */
    val VYSKY = listOf(40, 90, 100, 110, 120, PLNA_DP, 140, 155, 170, 185, 205)

    /**
     * Ukazat riadok hlasitosti? Vyska 0 = launcher ju nehlasi, vtedy ano
     * (predvolene su dve bunky).
     */
    fun sHlasitostou(vyskaDp: Int, zmensuje: Boolean): Boolean =
        vyskaDp <= 0 ||
            vyskaDp >= if (zmensuje) S_HLASITOSTOU_MIN_DP else S_HLASITOSTOU_BEZ_ZMENSOVANIA_DP

    /**
     * Kolko z plnej velkosti dostane obsah pri vyske [vyskaDp] a sirke
     * [sirkaDp]; 1 = plna. Bez hlasitosti sa nezmensuje — dva riadky sa
     * zmestia aj tak. Nad plnou velkostou rastie len pri znamej sirke.
     */
    fun mierka(vyskaDp: Int, sirkaDp: Int = 0): Float = when {
        vyskaDp in S_HLASITOSTOU_MIN_DP until PLNA_DP -> vyskaDp.toFloat() / PLNA_DP
        vyskaDp > PLNA_DP ->
            minOf(vyskaDp.toFloat() / PLNA_DP, NAJVIAC, naSirku(sirkaDp)).coerceAtLeast(1f)
        else -> 1f
    }

    /** Najvacsia mierka, pri ktorej horny riadok necha nazvu [NAZOV_MIN_DP]; 1 pri neznamej sirke. */
    fun naSirku(sirkaDp: Int): Float =
        if (sirkaDp <= 0) 1f else (sirkaDp - HORE_PEVNE_DP - NAZOV_MIN_DP).toFloat() / HORE_ROSTIE_DP
}
