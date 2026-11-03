package sk.lanmusic

import android.app.usage.NetworkStats
import android.app.usage.NetworkStatsManager
import android.content.Context
import android.content.SharedPreferences
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Handler
import android.os.Looper
import android.os.Process
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/**
 * Pocitadlo prenesenych dat — ZVLAST Wi-Fi, ZVLAST mobilne data.
 *
 * Tento subor je vo VSETKYCH appkach rovnaky (lisi sa len `package`) — rovnaka
 * dohoda ako pri `NastaveniaForm.kt` a `Vzhlad.kt`, viz docs/shared-standard.md.
 * Ked sa tu nieco meni, meni sa to vsade.
 *
 * **Cisla neratá appka, ale Android** (`NetworkStatsManager`) — tak, ako
 * spotrebu dat appky vidi system: stiahnute aj odoslane, vratane sifrovania,
 * hlaviciek a rezie siete, aj prenos cez VPN (Tailscale) zaratany na sieti pod
 * nou. Do 28. 10. 2026 si appky ratali samy nekomprimovanu velkost tiel
 * odpovedi; pri gzipe to bolo 4× viac nez skutocnost a co sa zabudlo
 * zaratat, nebolo vidiet vobec.
 *
 * **Preco rozdelene a nie jedno cislo.** Bajt cez Wi-Fi je zadarmo, bajt cez
 * simku stoji z pausalu. Wi-Fi/mobil rozlisuje Android podla siete, cez ktoru
 * prenos naozaj siel.
 *
 * **Ako to Android drzi** (AOSP `NetworkStatsService.getUidConfig`): spotreba
 * appky v 2-hodinovych usekoch, 90 dni. Ciastocne prekryty usek deli pomerne,
 * preto sa zaciatok zarovna na cely usek a pri vynulovani sa zapamata „zaklad"
 * — co uz v tom useku bolo — a potom sa odpocita.
 *
 * **Bez povoleni**: appka smie citat len vlastnu spotrebu
 * (`NetworkStatsAccess.Level.DEFAULT`) a otvorenie statistiky si vyziada ich
 * aktualizaciu (najviac raz za 15 s). Dotaz ale nesmie ist na hlavnom vlakne,
 * preto [nacitaj] a [vynuluj] bezia na pozadi a vysledok odovzdaju na hlavnom.
 *
 * **Texty su tu, nie v `strings.xml`.** Je to vynimka z pravidla a je zamerna:
 * subor sa kopiruje do vsetkych appiek a tie iste retazce v kazdom
 * `strings.xml` by sa rozisli uz pri prvej oprave preklepu.
 */
object Prenos {

    /** Kam sa prenos zarata. */
    enum class Siet { WIFI, MOBIL }

    // ---- texty pre obrazovku Nastaveni (viz poznamka v hlavicke suboru) ----

    const val NADPIS = "Prenesené dáta"
    const val VYNULOVAT = "Vynulovať počítadlo"
    const val NACITAVAM = "načítavam…"
    const val POZNAMKA =
        "Skutočne prenesené dáta tejto appky, stiahnuté aj odoslané, tak ako " +
        "ich ráta Android pri spotrebe dát appky. Wi-Fi a mobilné dáta zvlášť: " +
        "bajt cez Wi-Fi je zadarmo, bajt cez SIM z paušálu. Android drží " +
        "históriu 90 dní."

    private const val FILE = "prenos"
    private const val K_OD = "od"
    private const val K_ZAKLAD_WIFI = "zaklad_wifi"
    private const val K_ZAKLAD_MOBIL = "zaklad_mobil"

    /** Kluce stareho pocitadla (do 28. 10. 2026) — jeho odhady sa zahodia. */
    private val STARE_KLUCE = listOf("wifi_bajtov", "wifi_pocet", "mobil_bajtov", "mobil_pocet")

    /** Dlzka useku, v ktorom Android drzi spotrebu appky. */
    internal const val USEK_MS = 2L * 60 * 60 * 1000

    /** Starsie Android maze; den rezerva, aby sa nerátal napoly zmazany usek. */
    internal const val HISTORIA_MS = 89L * 24 * 60 * 60 * 1000

    private fun sp(ctx: Context): SharedPreferences =
        ctx.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** Stav pocitadla. Ciste cisla — obrazovka si z nich text poskladá sama. */
    data class Stav(
        val wifiBajtov: Long,
        val mobilBajtov: Long,
        /** Odkedy sa rata (ms). */
        val odMs: Long,
    ) {
        val spoluBajtov: Long get() = wifiBajtov + mobilBajtov
    }

    private val vlakno = Executors.newSingleThreadExecutor()
    private val hlavne by lazy { Handler(Looper.getMainLooper()) }

    /**
     * Zisti stav na pozadi a odovzda ho na hlavnom vlakne. Null = Android
     * statistiku nedal (stary system, chyba sluzby).
     */
    fun nacitaj(ctx: Context, hotovo: (Stav?) -> Unit) {
        val app = ctx.applicationContext
        vlakno.execute {
            val stav = runCatching { zisti(app) }.getOrNull()
            hlavne.post { hotovo(stav) }
        }
    }

    /** Zacne ratat od teraz; novy stav odovzda ako [nacitaj]. */
    // TYPE_WIFI/TYPE_MOBILE su zastarane pre ConnectivityManager, ale
    // NetworkStatsManager.querySummary ich stale chce ako typ siete.
    @Suppress("DEPRECATION")
    fun vynuluj(ctx: Context, hotovo: (Stav?) -> Unit) {
        val app = ctx.applicationContext
        vlakno.execute {
            val stav = runCatching {
                val teraz = System.currentTimeMillis()
                val zaciatok = zarovnaj(teraz)
                val wifi = zAndroidu(app, ConnectivityManager.TYPE_WIFI, zaciatok, teraz)
                val mobil = zAndroidu(app, ConnectivityManager.TYPE_MOBILE, zaciatok, teraz)
                sp(app).edit()
                    .putLong(K_OD, teraz)
                    .putLong(K_ZAKLAD_WIFI, wifi ?: 0L)
                    .putLong(K_ZAKLAD_MOBIL, mobil ?: 0L)
                    .apply()
                zisti(app)
            }.getOrNull()
            hlavne.post { hotovo(stav) }
        }
    }

    @Suppress("DEPRECATION")
    private fun zisti(ctx: Context): Stav? {
        val s = sp(ctx)
        if (STARE_KLUCE.any(s::contains)) {
            s.edit().apply { STARE_KLUCE.forEach { remove(it) } }.apply()
        }
        var od = s.getLong(K_OD, 0L)
        if (od == 0L) {
            // Nova instalacia: vsetko, co Android o appke vie.
            @Suppress("DEPRECATION")
            od = ctx.packageManager.getPackageInfo(ctx.packageName, 0).firstInstallTime
            s.edit().putLong(K_OD, od).apply()
        }
        val teraz = System.currentTimeMillis()
        val (odKedy, zaklad) = zaciatokAZaklad(od, teraz)
        val zaciatok = zarovnaj(odKedy)
        val wifi = zAndroidu(ctx, ConnectivityManager.TYPE_WIFI, zaciatok, teraz) ?: return null
        val mobil = zAndroidu(ctx, ConnectivityManager.TYPE_MOBILE, zaciatok, teraz) ?: return null
        return Stav(
            wifiBajtov = (wifi - if (zaklad) s.getLong(K_ZAKLAD_WIFI, 0L) else 0L).coerceAtLeast(0L),
            mobilBajtov = (mobil - if (zaklad) s.getLong(K_ZAKLAD_MOBIL, 0L) else 0L).coerceAtLeast(0L),
            odMs = odKedy,
        )
    }

    /** Zaciatok useku, v ktorom lezi [ms]. */
    internal fun zarovnaj(ms: Long): Long = ms - Math.floorMod(ms, USEK_MS)

    /**
     * Odkedy sa da poctivo ratat a ci plati zaklad z vynulovania. Ked je
     * vynulovanie starsie nez historia Androidu, jeho usek uz neexistuje —
     * rata sa od najstarsieho, co Android ma, a zaklad sa neodpocitava.
     */
    internal fun zaciatokAZaklad(od: Long, teraz: Long): Pair<Long, Boolean> {
        val najskor = teraz - HISTORIA_MS
        return if (od < najskor) najskor to false else od to true
    }

    /** Bajty appky (stiahnute + odoslane) na danom type siete od [od]. */
    private fun zAndroidu(ctx: Context, typ: Int, od: Long, teraz: Long): Long? {
        val nsm = ctx.getSystemService(NetworkStatsManager::class.java) ?: return null
        // Koniec za aktivnym usekom: aktivny usek sa potom rata cely, nie pomerne.
        val stats = nsm.querySummary(typ, null, od, teraz + USEK_MS) ?: return null
        val uid = Process.myUid()
        val bucket = NetworkStats.Bucket()
        var spolu = 0L
        try {
            while (stats.hasNextBucket()) {
                stats.getNextBucket(bucket)
                if (bucket.uid == uid) spolu += bucket.rxBytes + bucket.txBytes
            }
        } finally {
            stats.close()
        }
        return spolu
    }

    // -------------------------------- text ----------------------------------

    /**
     * Co sa ukaze v Nastaveniach.
     *
     * Nula sa vypise aj vtedy, ked na tej strane nic nebolo: prazdny riadok by
     * vyzeral ako chyba a „0 B cez mobilne data" je prave ta odpoved, kvoli
     * ktorej sa clovek na pocitadlo pozera.
     */
    fun popis(stav: Stav?): String {
        if (stav == null) return "Android spotrebu dát nedal."
        val datum = SimpleDateFormat("d.M.yyyy", Locale.getDefault()).format(Date(stav.odMs))
        return listOf(
            "Od $datum",
            "Wi-Fi: ${bajty(stav.wifiBajtov)}",
            "Mobilné dáta: ${bajty(stav.mobilBajtov)}",
            "Spolu: ${bajty(stav.spoluBajtov)}",
        ).joinToString("\n")
    }

    /**
     * Objem dat slovom, v tisickach ako systemove Nastavenia Androidu (od 8.0),
     * aby sa cisla dali porovnat.
     */
    fun bajty(b: Long): String = when {
        b >= 1_000_000L -> "%.1f MB".format(Locale("sk"), b / 1_000_000.0)
        b >= 1_000L -> "%.0f kB".format(Locale("sk"), b / 1_000.0)
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
