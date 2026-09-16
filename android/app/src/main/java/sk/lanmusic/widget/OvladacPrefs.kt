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

    fun ulozSkladbu(ctx: Context, titul: String, interpret: String, hra: Boolean) {
        sp(ctx).edit()
            .putString(K_TITUL, titul)
            .putString(K_INTERPRET, interpret)
            .putBoolean(K_HRA, hra)
            .apply()
    }
}
