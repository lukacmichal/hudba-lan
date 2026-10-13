package sk.lanmusic.ui

import android.content.Context
import android.os.SystemClock
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.PointerEventTimeoutCancellationException
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import sk.lanmusic.control.TouchpadSpojenie
import sk.lanmusic.control.TouchpadStav
import kotlin.math.abs
import kotlin.math.roundToInt

private const val PREFS = "touchpad"
private const val PREF_RYCHLOST = "rychlost"

/** Kolieskove jednotky Windowsu (120 = jeden zub) na 1 dp pohybu prstov. */
private const val KOLIESKO_NA_DP = 3f

/**
 * Telefon ako touchpad pre PC, na ktorom bezi prehravac.
 *
 * Gesta ako na notebooku: jeden prst hybe kurzorom, tuknutie je lavy klik,
 * tuknutie dvoma prstami pravy klik, dva prsty posuvaju (koliesko). Podrzanie
 * prsta bez pohybu (zavibruje) a potom tahanie = tahanie s lavym tlacidlom.
 */
@Composable
fun TouchpadScreen(ip: String, port: Int, onZavriet: () -> Unit) {
    val scope = rememberCoroutineScope()
    val spojenie = remember(ip, port) { TouchpadSpojenie(ip, port, scope) }
    DisposableEffect(spojenie) { onDispose { spojenie.zavri() } }
    val stav by spojenie.stav.collectAsState()

    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences(PREFS, Context.MODE_PRIVATE) }
    var rychlost by remember { mutableFloatStateOf(prefs.getFloat(PREF_RYCHLOST, 1.5f)) }

    BackHandler(onBack = onZavriet)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .systemBarsPadding()
            .imePadding()
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Touchpad", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.width(10.dp))
            Text(
                text = when (val s = stav) {
                    TouchpadStav.Necinny -> ip
                    TouchpadStav.Pripojeny -> "pripojené · $ip"
                    is TouchpadStav.Chyba -> s.sprava
                },
                style = MaterialTheme.typography.bodySmall,
                color = if (stav is TouchpadStav.Chyba) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onZavriet, modifier = Modifier.size(36.dp)) {
                Icon(Icons.Filled.Close, contentDescription = "Zavrieť touchpad")
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Rýchlosť", style = MaterialTheme.typography.bodySmall)
            Slider(
                value = rychlost,
                onValueChange = { rychlost = it },
                onValueChangeFinished = { prefs.edit().putFloat(PREF_RYCHLOST, rychlost).apply() },
                valueRange = 0.5f..4f,
                modifier = Modifier.padding(start = 10.dp).weight(1f),
            )
        }

        Plocha(
            rychlost = rychlost,
            posli = spojenie::posli,
            modifier = Modifier.fillMaxWidth().weight(1f),
        )

        Spacer(Modifier.height(6.dp))
        Row(Modifier.fillMaxWidth().height(56.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Tlacidlo("Ľavé", "l", spojenie::posli, Modifier.weight(2f))
            Tlacidlo("Stred", "m", spojenie::posli, Modifier.weight(1f))
            Tlacidlo("Pravé", "r", spojenie::posli, Modifier.weight(2f))
        }

        Spacer(Modifier.height(6.dp))
        Klavesy(spojenie::posli)
        Spacer(Modifier.height(6.dp))
        PisanieTextu(spojenie::posli)
    }
}

@Composable
private fun Plocha(rychlost: Float, posli: (String) -> Unit, modifier: Modifier) {
    val hustota = LocalDensity.current.density
    val slop = LocalViewConfiguration.current.touchSlop
    val dlheStlacenie = LocalViewConfiguration.current.longPressTimeoutMillis
    val haptika = LocalHapticFeedback.current
    val aktualnaRychlost by rememberUpdatedState(rychlost)

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(12.dp))
            .pointerInput(Unit) {
                // Zlomky bodu, ktore sa este neposlali — bez nich by pomaly
                // pohyb prstom kurzorom vobec nepohol.
                var zvysokX = 0f
                var zvysokY = 0f
                var kolieskoY = 0f
                var kolieskoX = 0f
                awaitEachGesture {
                    val prvy = awaitFirstDown(requireUnconsumed = false)
                    val zaciatok = prvy.uptimeMillis
                    var najviacPrstov = 1
                    var posunute = false      // jeden prst presiel za slop
                    var posuvane = false      // dva prsty posuvali
                    var tahanie = false
                    var drahaJeden = Offset.Zero
                    var drahaDva = Offset.Zero

                    while (true) {
                        val udalost = if (!posunute && !tahanie && najviacPrstov == 1) {
                            val zostava = dlheStlacenie - (SystemClock.uptimeMillis() - zaciatok)
                            try {
                                withTimeout(maxOf(1L, zostava)) {
                                    awaitPointerEvent()
                                }
                            } catch (_: PointerEventTimeoutCancellationException) {
                                // Prst drzi bez pohybu: zacina tahanie.
                                tahanie = true
                                haptika.performHapticFeedback(HapticFeedbackType.LongPress)
                                posli("d l")
                                continue
                            }
                        } else {
                            awaitPointerEvent()
                        }
                        val stlacene = udalost.changes.filter { it.pressed }
                        if (stlacene.isEmpty()) break
                        najviacPrstov = maxOf(najviacPrstov, stlacene.size)

                        if (stlacene.size == 1 && najviacPrstov == 1) {
                            val z = stlacene[0]
                            val d = z.position - z.previousPosition
                            drahaJeden += d
                            if (!posunute && drahaJeden.getDistance() > slop) posunute = true
                            if (posunute || tahanie) {
                                val dt = (z.uptimeMillis - z.previousUptimeMillis).coerceAtLeast(1)
                                val dpX = d.x / hustota
                                val dpY = d.y / hustota
                                // Zrychlenie: pomaly pohyb je presny, rychly
                                // prejde cez celu obrazovku.
                                val v = kotlin.math.sqrt(dpX * dpX + dpY * dpY) / dt
                                val nasobok = aktualnaRychlost * (1f + (v - 0.15f).coerceIn(0f, 2f) * 1.5f)
                                zvysokX += dpX * nasobok
                                zvysokY += dpY * nasobok
                                val mx = zvysokX.toInt()
                                val my = zvysokY.toInt()
                                if (mx != 0 || my != 0) {
                                    zvysokX -= mx
                                    zvysokY -= my
                                    posli("m $mx $my")
                                }
                            }
                        } else if (stlacene.size >= 2) {
                            // Posuv dvoma prstami: priemer ich pohybu.
                            var dx = 0f
                            var dy = 0f
                            stlacene.forEach {
                                dx += it.position.x - it.previousPosition.x
                                dy += it.position.y - it.previousPosition.y
                            }
                            dx /= stlacene.size * hustota
                            dy /= stlacene.size * hustota
                            drahaDva += Offset(dx, dy)
                            if (!posuvane && drahaDva.getDistance() * hustota > slop) posuvane = true
                            if (posuvane) {
                                // Obsah ide s prstami ako na telefone: prsty
                                // dole = koliesko hore (kladne vo Windowse).
                                kolieskoY += dy * KOLIESKO_NA_DP
                                kolieskoX -= dx * KOLIESKO_NA_DP
                                if (abs(kolieskoY) >= 10f) {
                                    val n = kolieskoY.roundToInt()
                                    kolieskoY -= n
                                    posli("s $n")
                                }
                                if (abs(kolieskoX) >= 10f) {
                                    val n = kolieskoX.roundToInt()
                                    kolieskoX -= n
                                    posli("h $n")
                                }
                            }
                        }
                        udalost.changes.forEach { it.consume() }
                    }

                    zvysokX = 0f; zvysokY = 0f; kolieskoX = 0f; kolieskoY = 0f
                    when {
                        tahanie -> posli("u l")
                        posunute || posuvane -> Unit
                        najviacPrstov >= 2 -> posli("c r")
                        else -> posli("c l")
                    }
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        Text(
            "1 prst: kurzor · ťuk: klik\n2 prsty: posun · ťuk 2 prstami: pravý klik\npodrž a ťahaj: ťahanie",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
            textAlign = TextAlign.Center,
        )
    }
}

/** Tlacidlo mysi: stlacenie a pustenie idu zvlast, takze sa da aj drzat. */
@Composable
private fun Tlacidlo(popis: String, kod: String, posli: (String) -> Unit, modifier: Modifier) {
    var drzane by remember { mutableStateOf(false) }
    Box(
        modifier = modifier
            .fillMaxHeight()
            .clip(RoundedCornerShape(10.dp))
            .background(
                if (drzane) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.surfaceVariant
            )
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(10.dp))
            .pointerInput(kod) {
                awaitEachGesture {
                    awaitFirstDown().consume()
                    drzane = true
                    posli("d $kod")
                    try {
                        do {
                            val u = awaitPointerEvent()
                            u.changes.forEach { it.consume() }
                        } while (u.changes.any { it.pressed })
                    } finally {
                        drzane = false
                        posli("u $kod")
                    }
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        Text(
            popis,
            color = if (drzane) MaterialTheme.colorScheme.onPrimary
            else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private val KLAVESY = listOf(
    "Esc" to "esc", "Tab" to "tab", "Enter" to "enter", "⌫" to "backspace",
    "←" to "left", "↑" to "up", "↓" to "down", "→" to "right",
    "Alt+Tab" to "alt+tab", "Win" to "win", "Medzera" to "space",
    "Ctrl+C" to "ctrl+c", "Ctrl+V" to "ctrl+v", "Alt+F4" to "alt+f4",
)

@Composable
private fun Klavesy(posli: (String) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        KLAVESY.forEach { (popis, kod) ->
            OutlinedButton(
                onClick = { posli("k $kod") },
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
            ) { Text(popis) }
        }
    }
}

/** Text sa posiela celý naraz, az po potvrdeni — Enter sa nepridava sam. */
@Composable
private fun PisanieTextu(posli: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    fun odosli() {
        if (text.isNotEmpty()) {
            // Novy riadok by v protokole ukoncil prikaz — PC ho z "t" aj tak
            // nevie dostat, Enter je samostatne tlacidlo.
            posli("t " + text.replace('\n', ' '))
            text = ""
        }
    }
    OutlinedTextField(
        value = text,
        onValueChange = { text = it },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        placeholder = { Text("Napísať na PC…") },
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
        keyboardActions = KeyboardActions(onSend = { odosli() }),
        trailingIcon = {
            IconButton(onClick = { odosli() }) {
                Icon(Icons.Filled.Send, contentDescription = "Poslať text")
            }
        },
    )
}
