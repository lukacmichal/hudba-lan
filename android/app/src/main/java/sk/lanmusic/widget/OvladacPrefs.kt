package sk.lanmusic.widget

import android.content.Context
import sk.lanmusic.discovery.DEFAULT_API_PORT

/**
 * Co widget vie o prehravaci, ked appka nebezi.
 *
 * Widget nemoze vyhladavat: UDP beacon sa caka az 10 sekund a widget dostane
 * na prekreslenie zlomok toho. Cita preto to iste ulozisko, do ktoreho pise
 * `UdpDiscoveryManager` — teda poslednu najdenu (alebo rucne zadanu) adresu.
 *
 * Nazov skladby sem pri kazdom pollnuti zapisuje appka. Bez toho by widget po
 * restarte telefonu ukazoval prazdny riadok, aj keby na PC hralo — a nemal by
 * z coho zistit, ze vobec o com pisat.
 *
 * Hlasitost (19. 9. 2026) sa uklada aj s CASOM, kedy bola zistena: widget
 * podla neho rozhoduje, ci smie dalsi krok pocitat od nej, alebo sa musi
 * najprv spytat PC ([CERSTVA_MS]).
 */
object OvladacPrefs {

    private const val FILE = "lan_music_prefs"

    // Rovnake kluce ako v UdpDiscoveryManager — zamerne, je to jedno ulozisko.
    private const val K_IP = "server_ip"
    private const val K_PORT = "server_port"
    private const val K_MANUAL_IP = "manual_ip"
    private const val K_MANUAL_PORT = "manual_port"

    private const val K_TITUL = "widget_titul"
    private const val K_INTERPRET = "widget_interpret"
    private const val K_HRA = "widget_hra"

    private const val K_HLASITOST = "widget_hlasitost"
    private const val K_HLASITOST_ZISTENA = "widget_hlasitost_zistena"
    private const val K_HLASITOST_NASTAVENA = "widget_hlasitost_nastavena"
    private const val K_PRED_STLMENIM = "widget_pred_stlmenim"

    /**
     * Ako dlho sa ulozenej hlasitosti veri ako zakladu pre dalsi krok.
     *
     * Dlhsie nie: hlasitost sa mohla medzitym zmenit na PC a krok od starej
     * hodnoty by nou skocil — z tichej noci na 85 jednym tuknutim. Kratsie
     * tiez nie: rychle tuknutia za sebou musia stavat na tom, co nastavilo
     * to predosle, a nie na odpovedi PC, ktore ho este nemusi mat spracovane.
     */
    const val CERSTVA_MS = 10_000L

    /**
     * Ako dlho po nastaveni z widgetu appka hlasitost NEPREPISE.
     *
     * Appka sa PC pyta kazde 2 s. Odpoved na otazku, ktora odisla tesne pred
     * tuknutim, nesie este povodnu hlasitost — a keby ju zapisala, dalsie
     * tuknutie by pocitalo od nej a jeden krok by sa stratil.
     */
    private const val OCHRANA_MS = 3_000L

    private fun sp(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /**
     * Adresa prehravaca, alebo null ked ziadna nie je znama.
     *
     * Rucne zadana ma prednost — rovnako ako pri vyhladavani v appke.
     */
    fun server(ctx: Context): Pair<String, Int>? {
        val p = sp(ctx)
        val rucna = p.getString(K_MANUAL_IP, "").orEmpty().trim()
        if (rucna.isNotEmpty()) return rucna to p.getInt(K_MANUAL_PORT, DEFAULT_API_PORT)
        val najdena = p.getString(K_IP, "").orEmpty().trim()
        if (najdena.isNotEmpty()) return najdena to p.getInt(K_PORT, DEFAULT_API_PORT)
        return null
    }

    fun titul(ctx: Context): String = sp(ctx).getString(K_TITUL, "").orEmpty()

    fun interpret(ctx: Context): String = sp(ctx).getString(K_INTERPRET, "").orEmpty()

    fun hra(ctx: Context): Boolean = sp(ctx).getBoolean(K_HRA, false)

    /** Hlasitost na PC (0–100), ako ju widget videl naposledy; -1 = nikdy. */
    fun hlasitost(ctx: Context): Int = sp(ctx).getInt(K_HLASITOST, -1)

    /**
     * Ulozena hlasitost, ked je z poslednych [CERSTVA_MS] — inak null a widget
     * sa musi spytat PC.
     */
    fun cerstvaHlasitost(ctx: Context, teraz: Long = System.currentTimeMillis()): Int? {
        val p = sp(ctx)
        val h = p.getInt(K_HLASITOST, -1)
        if (h < 0) return null
        return h.takeIf { teraz - p.getLong(K_HLASITOST_ZISTENA, 0L) in 0..CERSTVA_MS }
    }

    /** Hlasitost, ktoru widget prave zistil od PC. */
    fun ulozZistenuHlasitost(ctx: Context, hodnota: Int) {
        sp(ctx).edit()
            .putInt(K_HLASITOST, hodnota.coerceIn(0, 100))
            .putLong(K_HLASITOST_ZISTENA, System.currentTimeMillis())
            .apply()
    }

    /** Hlasitost, ktoru widget prave posiela na PC — od tejto chvile plati ona. */
    fun ulozNastavenuHlasitost(ctx: Context, hodnota: Int) {
        val teraz = System.currentTimeMillis()
        sp(ctx).edit()
            .putInt(K_HLASITOST, hodnota)
            .putLong(K_HLASITOST_ZISTENA, teraz)
            .putLong(K_HLASITOST_NASTAVENA, teraz)
            .apply()
    }

    /**
     * Prikaz na PC neodisiel: vrati povodnu hodnotu a zabudne, ze je cerstva.
     * Dalsie tuknutie sa tak PC najprv spyta, namiesto toho, aby stavalo na
     * hodnote, ktora nikdy neplatila.
     */
    fun hlasitostNeprisla(ctx: Context, povodna: Int) {
        sp(ctx).edit()
            .putInt(K_HLASITOST, povodna)
            .putLong(K_HLASITOST_ZISTENA, 0L)
            .putLong(K_HLASITOST_NASTAVENA, 0L)
            .apply()
    }

    fun predStlmenim(ctx: Context): Int = sp(ctx).getInt(K_PRED_STLMENIM, -1)

    fun ulozPredStlmenim(ctx: Context, hodnota: Int) {
        sp(ctx).edit().putInt(K_PRED_STLMENIM, hodnota).apply()
    }

    fun ulozSkladbu(
        ctx: Context,
        titul: String,
        interpret: String,
        hra: Boolean,
        hlasitost: Int,
    ) {
        val p = sp(ctx)
        val teraz = System.currentTimeMillis()
        val e = p.edit()
            .putString(K_TITUL, titul)
            .putString(K_INTERPRET, interpret)
            .putBoolean(K_HRA, hra)
        if (teraz - p.getLong(K_HLASITOST_NASTAVENA, 0L) !in 0..OCHRANA_MS) {
            e.putInt(K_HLASITOST, hlasitost.coerceIn(0, 100))
                .putLong(K_HLASITOST_ZISTENA, teraz)
        }
        e.apply()
    }
}
