package sk.lanmusic.widget

import android.app.Activity
import android.app.AlertDialog
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import kotlinx.coroutines.runBlocking
import sk.lanmusic.R
import sk.lanmusic.control.RemoteControlClient

private const val TAG = "PotvrdenieActivity"

/**
 * Otazka pred prikazom z widgetu, ktory sa neda vziat spat jednym tuknutim:
 * uspat / vypnut pocitac, "Spanok" a "Spanok 2".
 *
 * Preco to nie je priamo vo widgete: prehratie skladby sa da vziat spat dalsim
 * tuknutim, vypnutie pocitaca nie. Widget na ploche sa da trafit vreckom
 * a rozdiel medzi "preskoc skladbu" a "vypni notebook" musi byt vacsi nez
 * dva centimetre. "Spanok 2" tu je z rovnakeho dovodu: prepise, co prave hra,
 * a doplni skladby do playlistu. "Spanok" tiez — skok na tretiu od konca sa
 * jednym tuknutim spat nevrati, clovek by musel hladat, kde prestal.
 *
 * Obrazovka je dialogova a `excludeFromRecents` — nema ostavat v prehlade
 * poslednych appiek ako by to bola samostatna obrazovka.
 */
class PotvrdenieActivity : Activity() {

    override fun onCreate(stav: Bundle?) {
        super.onCreate(stav)
        val co = intent.getStringExtra(EXTRA_CO)
        if (co !in setOf(CO_SPANOK, CO_USPAT, CO_VYPNUT, CO_SPANOK2)) {
            finish()
            return
        }

        val server = OvladacPrefs.server(this)
        if (server == null) {
            Toast.makeText(this, R.string.w_bez_servera_rada, Toast.LENGTH_LONG).show()
            finish()
            return
        }

        val otazka = when (co) {
            CO_SPANOK -> R.string.w_spanok_otazka
            CO_USPAT -> R.string.w_uspat_otazka
            CO_SPANOK2 -> R.string.w_spanok2_otazka
            else -> R.string.w_vypnut_otazka
        }
        val potvrdenie = when (co) {
            CO_SPANOK -> R.string.w_spanok
            CO_USPAT -> R.string.w_uspat
            CO_SPANOK2 -> R.string.w_spanok2
            else -> R.string.w_vypnut
        }

        AlertDialog.Builder(this)
            .setMessage(getString(otazka, server.first))
            .setPositiveButton(potvrdenie) { _, _ -> posli(co!!, server) }
            .setNegativeButton(android.R.string.cancel) { _, _ -> finish() }
            .setOnCancelListener { finish() }
            .show()
    }

    private fun posli(co: String, server: Pair<String, Int>) {
        // Odozva HNED, este pred odoslanim: prikaz je fire-and-forget a bez
        // toastu by clovek nevedel, ci sa vobec nieco stalo.
        Toast.makeText(
            this,
            when (co) {
                CO_SPANOK -> R.string.w_spustam_spanok
                CO_USPAT -> R.string.w_uspavam
                CO_SPANOK2 -> R.string.w_pustam
                else -> R.string.w_vypinam
            },
            Toast.LENGTH_SHORT,
        ).show()
        val klient = RemoteControlClient(server.first, server.second)
        Thread {
            try {
                runBlocking {
                    when (co) {
                        CO_SPANOK -> klient.spanok()
                        CO_USPAT -> klient.sleep()
                        CO_SPANOK2 -> klient.sleep2()
                        else -> klient.shutdown()
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "prikaz $co zlyhal", e)
            }
        }.start()
        finish()
    }

    companion object {
        const val CO_SPANOK = "spanok"
        const val CO_USPAT = "uspat"
        const val CO_VYPNUT = "vypnut"
        const val CO_SPANOK2 = "spanok2"

        private const val EXTRA_CO = "co"

        fun pendingIntent(ctx: Context, co: String, kod: Int): PendingIntent =
            PendingIntent.getActivity(
                ctx, kod,
                Intent(ctx, PotvrdenieActivity::class.java)
                    .putExtra(EXTRA_CO, co)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
    }
}
