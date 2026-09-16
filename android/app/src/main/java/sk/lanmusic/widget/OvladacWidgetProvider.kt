package sk.lanmusic.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.util.Log
import android.util.TypedValue
import android.widget.RemoteViews
import kotlinx.coroutines.runBlocking
import sk.lanmusic.MainActivity
import sk.lanmusic.R
import sk.lanmusic.Vzhlad
import sk.lanmusic.control.RemoteControlClient
import sk.lanmusic.metadata.MetadataPoller

private const val TAG = "OvladacWidget"

/**
 * Widget na ovladanie prehravaca na pocitaci.
 *
 * **Preco widget vobec.** Appka je dialkove ovladanie a doteraz sa muselo
 * najprv otvorit — pri preskoceni jednej skladby to boli tri kroky namiesto
 * jedneho.
 *
 * **Widget nespusta appku ani sluzbu.** Prikaz je jeden kratky POST na
 * `/api/control`, presne ten isty, aky posiela appka; adresu si berie
 * z [OvladacPrefs], teda z toho, co appka naposledy nasla. Ked adresu este
 * nikto nema, widget to POVIE a tuknutie otvori appku — ta prehravac najde.
 *
 * **Spanok, uspanie, Spanok 2 a vypnutie pocitaca idu cez potvrdenie**
 * ([PotvrdenieActivity]). Su vpravo hore, oddelene od prevracania skladieb.
 * Ostatne tlacidla sa daju vziat spat dalsim tuknutim, tieto styri nie a na
 * ploche sa da trafit omylom vreckom.
 *
 * **Po prikaze si widget stiahne, co hra** (29. 8. 2026). Do vtedy nazov
 * skladby zapisovala VYLUCNE appka pri svojom pollovani — kto preskocil
 * skladbu z plochy, mal na widgete dalej nazov tej predoslej a jedina cesta
 * k spravnemu bola otvorit appku. Prehravac pritom prikaz vykonal; widget len
 * nemal odkial vediet, ako to dopadlo.
 */
class OvladacWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(ctx: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { prekresli(ctx, manager, it) }
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        super.onReceive(ctx, intent)
        val akcia = intent.action ?: return
        if (akcia !in PRIKAZY) return

        val server = OvladacPrefs.server(ctx)
        if (server == null) {
            Log.w(TAG, "adresa prehravaca nie je znama — otvor najprv appku")
            return
        }

        // Sietove volanie z receivera musi drzat proces nazive, kym dobehne —
        // bez goAsync() by ho system mohol zabit hned po navrate z onReceive.
        val hotovo = goAsync()
        val app = ctx.applicationContext
        Thread {
            try {
                val klient = RemoteControlClient(server.first, server.second)
                runBlocking {
                    when (akcia) {
                        AKCIA_PREV -> klient.prev()
                        AKCIA_PLAYPAUSE -> klient.playPause()
                        AKCIA_NEXT -> klient.next()
                        AKCIA_STOP -> klient.stop()
                    }
                }
                dotiahniStav(app, server.first, server.second)
            } catch (e: Exception) {
                // Vypadok siete widget nezhodi — prikaz sa proste nestal
                // a dalsie tuknutie ho posle znova.
                Log.w(TAG, "prikaz $akcia zlyhal", e)
            } finally {
                hotovo.finish()
            }
        }.start()
    }

    /**
     * Stiahne, co na pocitaci hra TERAZ, a prekresli widget.
     *
     * Pyta sa OPAKOVANE, nie raz: prehravac prikaz spracuje az za nejaky cas
     * (pri preskoceni skladby musi otvorit dalsi subor) a prva odpoved by este
     * niesla nazov tej predoslej — teda presne to, co widget uz ukazuje.
     * Ked sa stav zmeni, konci sa hned; ked nie (napr. STOP na zastavenom
     * prehravaci), po [POKUSOV] pokusoch sa zapise to posledne, co prislo.
     *
     * Cely cyklus je pod sekundu a pol, teda hlboko pod tym, co `goAsync()`
     * procesu drzi.
     */
    private fun dotiahniStav(app: Context, ip: String, port: Int) {
        val predtym = podpisStavu(app)
        var prislo = false
        // `for` s `break`, nie `repeat`: `return@repeat` by preskocil len jedno
        // kolo a cakalo by sa dalej aj po tom, co uz je jasne, ako to dopadlo.
        for (pokus in 1..POKUSOV) {
            Thread.sleep(PAUZA_MS)
            val stav = MetadataPoller.nacitaj(ip, port) ?: continue
            prislo = true
            OvladacPrefs.ulozSkladbu(
                app,
                titul = stav.title,
                interpret = stav.artist,
                hra = stav.state == "playing",
            )
            if (podpisStavu(app) != predtym) break
        }
        // Prehravac neodpovedal? Prekresli sa aj tak — widget tak ostane taky,
        // aky bol, namiesto toho, aby zamrzol s polovicnym stavom.
        if (!prislo) Log.w(TAG, "stav po prikaze sa nepodarilo stiahnut")
        prekresliVsetky(app)
    }

    /** Co widget prave ukazuje — na porovnanie, ci sa uz nieco zmenilo. */
    private fun podpisStavu(app: Context): String =
        OvladacPrefs.titul(app) + "|" + OvladacPrefs.interpret(app) +
            "|" + OvladacPrefs.hra(app)

    companion object {
        const val AKCIA_PREV = "sk.lanmusic.widget.PREV"
        const val AKCIA_PLAYPAUSE = "sk.lanmusic.widget.PLAYPAUSE"
        const val AKCIA_NEXT = "sk.lanmusic.widget.NEXT"
        const val AKCIA_STOP = "sk.lanmusic.widget.STOP"

        private val PRIKAZY = setOf(AKCIA_PREV, AKCIA_PLAYPAUSE, AKCIA_NEXT, AKCIA_STOP)

        /** Kolkokrat sa po prikaze spytat, co hra, a s akou pauzou medzi tym. */
        private const val POKUSOV = 5
        private const val PAUZA_MS = 250L

        // Zakladne velkosti pisma vo widgete (sp) — rovnake ako v layoute.
        // Nasobia sa krokom PRE WIDGET z Nastaveni: widget kresli launcher
        // a `fontScale` z kontextu appky nepocuva.
        private const val SP_TITUL = 15f
        private const val SP_INTERPRET = 13f

        fun prekresliVsetky(ctx: Context) {
            val manager = AppWidgetManager.getInstance(ctx)
            val ids = manager.getAppWidgetIds(
                ComponentName(ctx, OvladacWidgetProvider::class.java)
            )
            ids.forEach { prekresli(ctx, manager, it) }
        }

        private fun prekresli(ctx: Context, manager: AppWidgetManager, id: Int) {
            val v = RemoteViews(ctx.packageName, R.layout.widget_ovladac)
            val server = OvladacPrefs.server(ctx)

            // Cierny rezim z Nastaveni appky. Widget kresli launcher, takze
            // sa mu pozadie musi povedat vyslovne — sam o nastaveni appky nevie.
            // Ide o baterku, nie o vzhlad: widget je na ploche stale a na OLED
            // sa cierny pixel nerozsvieti vobec.
            v.setInt(
                R.id.w_koren, "setBackgroundResource",
                if (Vzhlad.jeTmavy(ctx)) R.drawable.widget_ovladac_bg_cierny
                else R.drawable.widget_ovladac_bg,
            )

            if (server == null) {
                // Bez adresy by tlacidla len ticho nefungovali. Radsej to
                // povedz — a nechaj cestu, ako to napravit.
                v.setTextViewText(R.id.w_titul, ctx.getString(R.string.w_bez_servera))
                v.setTextViewText(R.id.w_interpret, ctx.getString(R.string.w_bez_servera_rada))
            } else {
                val titul = OvladacPrefs.titul(ctx)
                v.setTextViewText(
                    R.id.w_titul,
                    titul.ifBlank { ctx.getString(R.string.w_nic_nehra) },
                )
                v.setTextViewText(R.id.w_interpret, OvladacPrefs.interpret(ctx))
            }

            val faktor = Vzhlad.faktorWidgetu(ctx)
            v.setTextViewTextSize(R.id.w_titul, TypedValue.COMPLEX_UNIT_SP, SP_TITUL * faktor)
            v.setTextViewTextSize(
                R.id.w_interpret, TypedValue.COMPLEX_UNIT_SP, SP_INTERPRET * faktor,
            )

            v.setImageViewResource(
                R.id.w_playpause,
                if (OvladacPrefs.hra(ctx)) R.drawable.ic_pause else R.drawable.ic_play,
            )

            v.setOnClickPendingIntent(R.id.w_prev, prikaz(ctx, AKCIA_PREV, 1))
            v.setOnClickPendingIntent(R.id.w_playpause, prikaz(ctx, AKCIA_PLAYPAUSE, 2))
            v.setOnClickPendingIntent(R.id.w_next, prikaz(ctx, AKCIA_NEXT, 3))
            v.setOnClickPendingIntent(R.id.w_stop, prikaz(ctx, AKCIA_STOP, 4))

            // Nevratne prikazy nejdu priamo — otvori sa otazka.
            v.setOnClickPendingIntent(
                R.id.w_spanok,
                PotvrdenieActivity.pendingIntent(ctx, PotvrdenieActivity.CO_SPANOK, 8),
            )
            v.setOnClickPendingIntent(
                R.id.w_sleep,
                PotvrdenieActivity.pendingIntent(ctx, PotvrdenieActivity.CO_USPAT, 5),
            )
            v.setOnClickPendingIntent(
                R.id.w_sleep2,
                PotvrdenieActivity.pendingIntent(ctx, PotvrdenieActivity.CO_SPANOK2, 7),
            )
            v.setOnClickPendingIntent(
                R.id.w_shutdown,
                PotvrdenieActivity.pendingIntent(ctx, PotvrdenieActivity.CO_VYPNUT, 6),
            )

            // Tuknutie na nazov otvori appku (a s nou vyhladavanie prehravaca).
            v.setOnClickPendingIntent(
                R.id.w_titul,
                PendingIntent.getActivity(
                    ctx, 0,
                    Intent(ctx, MainActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
            )

            manager.updateAppWidget(id, v)
        }

        private fun prikaz(ctx: Context, akcia: String, kod: Int): PendingIntent =
            PendingIntent.getBroadcast(
                ctx, kod,
                Intent(ctx, OvladacWidgetProvider::class.java).setAction(akcia),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
    }
}
