package sk.lanmusic

import android.content.Context
import android.content.SharedPreferences
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Pocitadlo prenesenych dat — ZVLAST Wi-Fi, ZVLAST mobilne data.
 *
 * Tento subor je vo VSETKYCH appkach rovnaky (lisi sa len `package`) — rovnaka
 * dohoda ako pri `NastaveniaForm.kt` a `Vzhlad.kt`, viz docs/shared-standard.md.
 * Ked sa tu nieco meni, meni sa to vsade.
 *
 * **Preco rozdelene a nie jedno cislo.** Bajt cez Wi-Fi je zadarmo, bajt cez
 * simku stoji z pausalu. Jedno spolocne cislo tie dva svety zlucilo a tym
 * zakrylo jedinu otazku, na ktoru ma pocitadlo odpovedat: „stiahla mi appka
 * nieco za peniaze?" Appka moze mat mesacne 20 MB a byt v poriadku, ked je
 * z toho 19,9 MB z domacej Wi-Fi — a moze mat 2 MB a byt problem, ked su
 * vsetky cez data.
 *
 * **Rozhoduje PRENOSOVA VRSTVA, nie meranost siete.** Zadanie znie „Wi-Fi
 * proti simke"; `isActiveNetworkMetered` by hotspot kolegu (Wi-Fi, ale
 * merana) zaratal medzi mobilne data. Meranost sa pouzije az vtedy, ked sa
 * vrstva zistit neda — vtedy je „radsej to zarataj medzi data" poctivejsi
 * odhad nez „radsej medzi Wi-Fi".
 *
 * **Vlastny subor prefs, nie `Prefs` appky.** Vdaka tomu sa da tento subor
 * do dalsej appky len skopirovat (zmenit `package`) a vynulovanie pocitadla
 * sa nema ako dotknut nastaveni.
 *
 * **Texty su tu, nie v `strings.xml`.** Je to vynimka z pravidla a je zamerna:
 * subor sa kopiruje do deviatich appiek a devat kopii tych istych retazcov
 * v deviatich `strings.xml` by sa rozislo uz pri prvej oprave preklepu.
 * Obrazovka Nastaveni si tak vypyta [popis] a nema co pokazit.
 *
 * Ratá sa **nekomprimovana** velkost tela odpovede — horny odhad, nie
 * prikraslenie. Hlavicky a rezia TCP sa neratajú; appka ich nevidi.
 */
object Prenos {

    /** Kam sa prenos zarata. */
    enum class Siet { WIFI, MOBIL }

    // ---- texty pre obrazovku Nastaveni (viz poznamka v hlavicke suboru) ----

    const val NADPIS = "Prenesené dáta"
    const val VYNULOVAT = "Vynulovať počítadlo"
    const val POZNAMKA =
        "Ráta sa nekomprimovaná veľkosť prenosu, teda horný odhad. Wi-Fi " +
        "a mobilné dáta zvlášť: bajt cez Wi-Fi je zadarmo, bajt cez SIM " +
        "z paušálu."

    private const val FILE = "prenos"

    private const val K_WIFI_B = "wifi_bajtov"
    private const val K_WIFI_N = "wifi_pocet"
    private const val K_MOBIL_B = "mobil_bajtov"
    private const val K_MOBIL_N = "mobil_pocet"
    private const val K_OD = "od"

    private fun sp(ctx: Context): SharedPreferences =
        ctx.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /**
     * Stav pocitadla. Ciste cisla bez Androidu — obrazovka si z nich text
     * poskladá sama a test ich vie vyrobit bez emulatora.
     */
    data class Stav(
        val wifiBajtov: Long,
        val wifiPocet: Int,
        val mobilBajtov: Long,
        val mobilPocet: Int,
        /** Odkedy sa rata (ms). 0 = este sa neratalo nic. */
        val odMs: Long,
    ) {
        val spoluBajtov: Long get() = wifiBajtov + mobilBajtov
        val spoluPocet: Int get() = wifiPocet + mobilPocet
        val prazdny: Boolean get() = spoluPocet == 0
    }

    // ------------------------------- zapis ----------------------------------

    /**
     * Zarata prenos. Siet sa zistuje TERAZ, v okamihu prenosu — spatne sa uz
     * povedat neda, cez co to preslo.
     *
     * Nulovy alebo zaporny pocet bajtov sa ignoruje: zlyhane stiahnutie nie je
     * stiahnutie a v pocte by robilo zmatok.
     */
    fun zapis(ctx: Context, bajtov: Long) {
        if (bajtov <= 0L) return
        zapis(ctx, bajtov, akaSiet(ctx))
    }

    /** To iste s vyslovne urcenou sietou — pouziva sa v testoch. */
    fun zapis(ctx: Context, bajtov: Long, siet: Siet) {
        if (bajtov <= 0L) return
        val s = sp(ctx)
        val e = s.edit()
        if (s.getLong(K_OD, 0L) == 0L) e.putLong(K_OD, System.currentTimeMillis())
        when (siet) {
            Siet.WIFI -> e
                .putLong(K_WIFI_B, s.getLong(K_WIFI_B, 0L) + bajtov)
                .putInt(K_WIFI_N, s.getInt(K_WIFI_N, 0) + 1)
            Siet.MOBIL -> e
                .putLong(K_MOBIL_B, s.getLong(K_MOBIL_B, 0L) + bajtov)
                .putInt(K_MOBIL_N, s.getInt(K_MOBIL_N, 0) + 1)
        }
        e.apply()
    }

    /**
     * Nazbierane bajty pre klientov, ktori Context nemaju.
     *
     * Sietove kniznice appiek (`YahooKlient`, `OllamaClient`, scrapery
     * tankomatu) su zamerne ciste objekty bez Androidu, aby sa dali testovat.
     * Nemaju teda odkial vziat `Context` — nazbieraju sem a ten, kto ich vola
     * a Context ma, to jednym riadkom [odovzdaj]-a.
     *
     * Ked appku system zabije skor, nez sa odovzda, o par kilobajtov v pocte
     * pride. Je to horny odhad naopak, ale rozdiel je radovo mensi nez chyba,
     * ktorou je uz samotne ratanie nekomprimovanej velkosti.
     */
    @Volatile
    private var nazbierane: Long = 0L

    @Synchronized
    fun nazbieraj(bajtov: Long) {
        if (bajtov > 0L) nazbierane += bajtov
    }

    /** Presunie nazbierane do pocitadla. Nula nic nespravi. */
    @Synchronized
    fun odovzdaj(ctx: Context) {
        val b = nazbierane
        nazbierane = 0L
        zapis(ctx, b)
    }

    fun stav(ctx: Context): Stav = sp(ctx).let {
        Stav(
            wifiBajtov = it.getLong(K_WIFI_B, 0L),
            wifiPocet = it.getInt(K_WIFI_N, 0),
            mobilBajtov = it.getLong(K_MOBIL_B, 0L),
            mobilPocet = it.getInt(K_MOBIL_N, 0),
            odMs = it.getLong(K_OD, 0L),
        )
    }

    fun vynuluj(ctx: Context) {
        sp(ctx).edit()
            .putLong(K_WIFI_B, 0L).putInt(K_WIFI_N, 0)
            .putLong(K_MOBIL_B, 0L).putInt(K_MOBIL_N, 0)
            .putLong(K_OD, System.currentTimeMillis())
            .apply()
    }

    // -------------------------------- text ----------------------------------

    /**
     * Co sa ukaze v Nastaveniach.
     *
     * Nula sa vypise aj vtedy, ked na tej strane nic nebolo: prazdny riadok by
     * vyzeral ako chyba a „0 B cez mobilne data" je prave ta odpoved, kvoli
     * ktorej sa clovek na pocitadlo pozera.
     */
    fun popis(ctx: Context): String {
        val s = stav(ctx)
        if (s.prazdny) return "zatiaľ nič"
        val datum = SimpleDateFormat("d.M.yyyy", Locale.getDefault()).format(Date(s.odMs))
        return listOf(
            "Od $datum",
            "Wi-Fi: ${bajty(s.wifiBajtov)} (${s.wifiPocet} prenosov)",
            "Mobilné dáta: ${bajty(s.mobilBajtov)} (${s.mobilPocet} prenosov)",
            "Spolu: ${bajty(s.spoluBajtov)}",
        ).joinToString("\n")
    }

    /**
     * Objem dat slovom. Vlastny, nie z `Format` appky: ten kazda appka nema
     * a tento subor ma byt sam o sebe uplny.
     */
    fun bajty(b: Long): String = when {
        b >= 1024L * 1024 -> "%.1f MB".format(Locale("sk"), b / 1048576.0)
        b >= 1024 -> "${b / 1024} kB"
        else -> "$b B"
    }

    // -------------------------------- siet ----------------------------------

    /**
     * Cez co je telefon prave pripojeny.
     *
     * Bez siete (lietadlovy rezim) vrati [Siet.MOBIL] — je to jedno, lebo
     * bez siete sa aj tak nic neprenesie, a keby predsa, byt opatrny je
     * spravnejsie nez tvarit sa, ze to bolo zadarmo.
     */
    fun akaSiet(ctx: Context): Siet {
        val cm = ctx.applicationContext
            .getSystemService(ConnectivityManager::class.java) ?: return Siet.MOBIL
        val schopnosti = cm.getNetworkCapabilities(cm.activeNetwork)
        return when {
            schopnosti == null -> if (cm.isActiveNetworkMetered) Siet.MOBIL else Siet.WIFI
            schopnosti.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> Siet.MOBIL
            schopnosti.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> Siet.WIFI
            schopnosti.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> Siet.WIFI
            // VPN a ine: rozhodne meranost. VPN bezi NAD nejakou sietou a tu
            // schopnosti tunela uz neprezradia.
            else -> if (cm.isActiveNetworkMetered) Siet.MOBIL else Siet.WIFI
        }
    }

    /**
     * Je appka prave na mobilnych datach?
     *
     * Pouziva sa tam, kde sa appka ma na datach drzat spat (automaticke
     * stahovanie pri otvoreni, ticha kontrola aktualizacie).
     */
    fun naMobilnychDatach(ctx: Context): Boolean = akaSiet(ctx) == Siet.MOBIL
}
