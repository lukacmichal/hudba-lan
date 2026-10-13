package sk.lanmusic.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.util.TypedValue
import android.view.View
import android.widget.RemoteViews
import kotlinx.coroutines.runBlocking
import java.util.concurrent.Executors
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
 *
 * **Hlasitost** (19. 9. 2026): pas ako posuvnik — tuknes kam chces a hlasitost
 * je tam ([HlasitostPas]), reproduktor vedla neho stlmi. Posiela sa ten isty
 * `setVolume` s hodnotou 0–100, aky posiela posuvnik v appke — PC prehravac
 * preto netreba menit. Podrobnosti pri [zmenHlasitost].
 */
class OvladacWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(ctx: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { prekresli(ctx, manager, it) }
    }

    // Zmena velkosti widgetu: riadok hlasitosti sa podla vysky ukaze/skryje.
    override fun onAppWidgetOptionsChanged(
        ctx: Context,
        manager: AppWidgetManager,
        id: Int,
        moznosti: Bundle,
    ) {
        prekresli(ctx, manager, id)
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        super.onReceive(ctx, intent)
        val akcia = intent.action ?: return
        if (akcia !in PRIKAZY && akcia !in PRIKAZY_HLASITOSTI) return

        val server = OvladacPrefs.server(ctx)
        if (server == null) {
            Log.w(TAG, "adresa prehravaca nie je znama — otvor najprv appku")
            return
        }

        // Sietove volanie z receivera musi drzat proces nazive, kym dobehne —
        // bez goAsync() by ho system mohol zabit hned po navrate z onReceive.
        val hotovo = goAsync()
        val app = ctx.applicationContext

        if (akcia in PRIKAZY_HLASITOSTI) {
            // -1 = stlmenie; pri tuknuti na pas je to hodnota dielika.
            val hodnota = intent.getIntExtra(EXTRA_HLASITOST, -1)
            // Jedno vlakno pre vsetky tuknutia na hlasitost, nie nove pre
            // kazde: dve rychle tuknutia na pas musia na PC dojst v PORADI,
            // v akom padli. Subezne by to prve mohlo dojst neskor a prepisat
            // hodnotu, na ktorej sa prst naozaj zastavil.
            RAD_HLASITOSTI.execute {
                try {
                    zmenHlasitost(app, server.first, server.second, akcia, hodnota)
                } catch (e: Exception) {
                    Log.w(TAG, "hlasitost $akcia zlyhala", e)
                } finally {
                    hotovo.finish()
                }
            }
            return
        }

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
                hlasitost = stav.volume,
            )
            if (podpisStavu(app) != predtym) break
        }
        // Prehravac neodpovedal? Prekresli sa aj tak — widget tak ostane taky,
        // aky bol, namiesto toho, aby zamrzol s polovicnym stavom.
        if (!prislo) Log.w(TAG, "stav po prikaze sa nepodarilo stiahnut")
        prekresliVsetky(app)
    }

    /**
     * Tuknutie na pas alebo na reproduktor. Bezi na [RAD_HLASITOSTI], teda
     * vzdy len jedno naraz.
     *
     * **Pas** posiela rovno hodnotu dielika, na ktory prst tukol. Od toho, co
     * je na PC nastavene teraz, nezavisi — netreba sa teda nic pytat.
     *
     * **Stlmenie** zavisi: vrátit sa ma na to, co hralo predtym, a stlmit sa
     * da len nieco nenulove. Hodnota vo widgete moze byt stara (appka ju
     * zapisuje, len kym bezi, a na PC sa dala medzitym zmenit), preto sa
     * pouzije, len ked je z poslednych [OvladacPrefs.CERSTVA_MS]; inak sa PC
     * najprv spyta. Ked neodpovie, nestane sa nic — prikaz by aj tak neodisiel.
     *
     * **Pas sa prekresli hned**, este pred odoslanim. Odozva z PC trva a bez
     * nej by clovek nevedel, ci tuknutie vobec trafil. Ked prikaz neprejde,
     * pas sa vrati tam, kde bol.
     */
    private fun zmenHlasitost(
        app: Context,
        ip: String,
        port: Int,
        akcia: String,
        hodnota: Int,
    ) {
        val povodna: Int
        val ciel: Int
        if (akcia == AKCIA_NASTAV_HLASITOST) {
            if (hodnota !in HlasitostPas.MIN..HlasitostPas.MAX) return
            povodna = OvladacPrefs.hlasitost(app)
            ciel = hodnota
        } else {
            val zaklad = OvladacPrefs.cerstvaHlasitost(app)
                ?: MetadataPoller.nacitaj(ip, port)?.volume
                    ?.also { OvladacPrefs.ulozZistenuHlasitost(app, it) }
            if (zaklad == null) {
                Log.w(TAG, "hlasitost sa nepodarilo zistit — prehravac neodpoveda")
                return
            }
            povodna = zaklad
            ciel = HlasitostPas.prepniStlmenie(zaklad, OvladacPrefs.predStlmenim(app))
            if (zaklad > 0) OvladacPrefs.ulozPredStlmenim(app, zaklad)
        }

        OvladacPrefs.ulozNastavenuHlasitost(app, ciel)
        prekresliVsetky(app)

        val odoslane = runBlocking { RemoteControlClient(ip, port).setVolume(ciel) }
        if (odoslane.isFailure) {
            Log.w(TAG, "setVolume $ciel neodisiel", odoslane.exceptionOrNull())
            OvladacPrefs.hlasitostNeprisla(app, povodna)
            prekresliVsetky(app)
        }
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

        const val AKCIA_NASTAV_HLASITOST = "sk.lanmusic.widget.NASTAV_HLASITOST"
        const val AKCIA_STLMIT = "sk.lanmusic.widget.STLMIT"
        const val EXTRA_HLASITOST = "hlasitost"

        private val PRIKAZY_HLASITOSTI = setOf(AKCIA_NASTAV_HLASITOST, AKCIA_STLMIT)

        /**
         * Kody PendingIntentov dielikov pasu: 100 az 119. Kazdy dielik musi mat
         * VLASTNY kod — dva PendingIntenty, ktore sa lisia len extra hodnotou,
         * su pre Android ten isty a vsetky dieliky by nastavovali to iste.
         */
        private const val KOD_PAS = 100

        /** Vid [zmenHlasitost] a [onReceive] — tuknutia na hlasitost idu po jednom. */
        private val RAD_HLASITOSTI = Executors.newSingleThreadExecutor()

        /**
         * Pod touto vyskou (dp) sa riadok hlasitosti skryje. Tri riadky
         * potrebuju 128 dp (odsadenie 16 + 32 + 4 + 40 + 4 + 32); pri 120 sa
         * tlacidlam prehravania oreze len okraj, nie ikonka.
         */
        private const val VYSKA_S_HLASITOSTOU_DP = 120

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
            // Vysku hlasi launcher v dp. Nula = nehlasi (stary launcher).
            // MIN_HEIGHT ako v appke Pocasie, kde sa na domacom telefone
            // osvedcila.
            val vyska = manager.getAppWidgetOptions(id)
                .getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 0)
            manager.updateAppWidget(id, vytvor(ctx, vyska))
        }

        /**
         * Obsah widgetu. Oddelene od [prekresli], aby sa dal nafuknut aj bez
         * launchera — inak sa da widget vyskusat len na ploche telefonu.
         *
         * @param vyskaDp vyska widgetu podla launchera, 0 = neznama
         */
        internal fun vytvor(ctx: Context, vyskaDp: Int): RemoteViews {
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

            // Na widgete nizsom nez dve bunky sa riadok hlasitosti skryje;
            // vyska 0 (launcher ju nehlasi) = ukazat, predvolene su dve bunky.
            v.setViewVisibility(
                R.id.w_hlasitost_riadok,
                if (vyskaDp in 1 until VYSKA_S_HLASITOSTOU_DP) View.GONE else View.VISIBLE,
            )
            pas(ctx, v)

            v.setImageViewResource(
                R.id.w_playpause,
                if (OvladacPrefs.hra(ctx)) R.drawable.ic_pause else R.drawable.ic_play,
            )

            v.setOnClickPendingIntent(R.id.w_prev, prikaz(ctx, AKCIA_PREV, 1))
            v.setOnClickPendingIntent(R.id.w_playpause, prikaz(ctx, AKCIA_PLAYPAUSE, 2))
            v.setOnClickPendingIntent(R.id.w_next, prikaz(ctx, AKCIA_NEXT, 3))
            v.setOnClickPendingIntent(R.id.w_stop, prikaz(ctx, AKCIA_STOP, 4))
            // Kod 11: 1–8 su obsadene tlacidlami vyssie a nizsie, 100+ pasom.
            v.setOnClickPendingIntent(R.id.w_stlmit, prikaz(ctx, AKCIA_STLMIT, 11))

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

            // Mys otvori appku rovno na touchpade (MainActivity.EXTRA_TOUCHPAD).
            // Vlastny request kod 9 — s nazvom (0) sa lisi len extra hodnotou
            // a dva take PendingIntenty by Android zlucil do jedneho.
            v.setOnClickPendingIntent(
                R.id.w_touchpad,
                PendingIntent.getActivity(
                    ctx, 9,
                    Intent(ctx, MainActivity::class.java)
                        .putExtra(MainActivity.EXTRA_TOUCHPAD, true)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
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

            return v
        }

        /**
         * Pas hlasitosti: vypln po aktualnu hodnotu a nad nou dieliky, kazdy
         * s vlastnym "nastav na …" (preco to nie je SeekBar, je vo
         * widget_ovladac.xml).
         *
         * `removeAllViews` nie je navyse: ked ma nova podoba widgetu ten isty
         * layout ako predosla, launcher ju nenafukne od nuly, ale prehra
         * prikazy na uz existujucich views. Bez vycistenia by pri kazdom
         * prekresleni pribudlo dalsich dvadsat dielikov.
         */
        private fun pas(ctx: Context, v: RemoteViews) {
            val hlasitost = OvladacPrefs.hlasitost(ctx)
            // Neznama hlasitost (-1) = prazdny pas. Doplni ju appka pri
            // pollovani alebo prve tuknutie.
            v.setProgressBar(R.id.w_pas, HlasitostPas.MAX, hlasitost.coerceAtLeast(0), false)
            v.setImageViewResource(
                R.id.w_stlmit,
                if (hlasitost == 0) R.drawable.ic_hlasitost_stlmena else R.drawable.ic_hlasitost,
            )

            v.removeAllViews(R.id.w_pas_dotyk)
            for (i in 0 until HlasitostPas.DIELIKOV) {
                val hodnota = HlasitostPas.hodnotaDielika(i)
                val dielik = RemoteViews(ctx.packageName, R.layout.widget_hlasitost_dielik)
                dielik.setOnClickPendingIntent(
                    R.id.w_dielik,
                    PendingIntent.getBroadcast(
                        ctx, KOD_PAS + i,
                        Intent(ctx, OvladacWidgetProvider::class.java)
                            .setAction(AKCIA_NASTAV_HLASITOST)
                            .putExtra(EXTRA_HLASITOST, hodnota),
                        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                    ),
                )
                dielik.setContentDescription(
                    R.id.w_dielik, ctx.getString(R.string.w_hlasitost_na, hodnota),
                )
                v.addView(R.id.w_pas_dotyk, dielik)
            }
        }

        private fun prikaz(ctx: Context, akcia: String, kod: Int): PendingIntent =
            PendingIntent.getBroadcast(
                ctx, kod,
                Intent(ctx, OvladacWidgetProvider::class.java).setAction(akcia),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
    }
}
