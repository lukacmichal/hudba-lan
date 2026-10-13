package sk.lanmusic.ui

import android.app.Activity
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import sk.lanmusic.discovery.DiscoveryState
import sk.lanmusic.playlist.PlaylistFilter
import sk.lanmusic.playlist.PlaylistItem
import sk.lanmusic.service.PlaybackState
import sk.lanmusic.update.UpdateConfig
import sk.lanmusic.update.UpdateState
import sk.lanmusic.Prenos
import sk.lanmusic.Vzhlad
import sk.lanmusic.widget.OvladacWidgetProvider

@Composable
fun PlayerScreen(
    uiState: PlayerUiState,
    onPrev: () -> Unit,
    onPlayPause: () -> Unit,
    onNext: () -> Unit,
    onStop: () -> Unit,
    onSeek: (Long) -> Unit,
    onVolume: (Int) -> Unit,
    onToggleMute: () -> Unit,
    onPlayIndex: (Int) -> Unit,
    onShutdown: () -> Unit,
    onSleep: () -> Unit,
    onSleep2: () -> Unit,
    onToggleListening: () -> Unit,
    onReconnectClicked: () -> Unit,
    onExitClicked: () -> Unit,
    onCheckUpdates: () -> Unit,
    onConfirmUpdate: () -> Unit,
    onInstallUpdate: () -> Unit,
    onDismissUpdate: () -> Unit,
    onSaveUpdateSettings: (UpdateConfig) -> Unit,
    onSaveManualServer: (String, Int) -> Unit,
    onTestConnection: suspend (UpdateConfig) -> String,
    touchpadZiadost: Boolean = false,
    onTouchpadZiadostVybavena: () -> Unit = {},
) {
    val isFound = uiState.discovery is DiscoveryState.Found
    // null = no dialog; "sleep" / "shutdown" / "sleep2" = confirm that action
    var pendingPowerAction by remember { mutableStateOf<String?>(null) }
    var menuExpanded by remember { mutableStateOf(false) }
    var showUpdateSettings by remember { mutableStateOf(false) }
    // Only a user-triggered check reports "up to date" / errors; the silent
    // startup check must stay invisible.
    var manualCheck by remember { mutableStateOf(false) }
    var updateMessage by remember { mutableStateOf<String?>(null) }
    var showTouchpad by rememberSaveable { mutableStateOf(false) }
    // Mys vo widgete: touchpad sa ukaze, hned ako je PC najdeny (dovtedy
    // bezi hlavna obrazovka s hladanim servera).
    LaunchedEffect(touchpadZiadost) {
        if (touchpadZiadost) {
            showTouchpad = true
            onTouchpadZiadostVybavena()
        }
    }

    LaunchedEffect(uiState.updateState) {
        if (!manualCheck) return@LaunchedEffect
        val message = when (val s = uiState.updateState) {
            is UpdateState.UpToDate -> "Máš najnovšiu verziu."
            is UpdateState.NotConfigured -> "Najprv zadaj údaje v Nastaveniach aktualizácií."
            is UpdateState.Failed -> s.reason
            else -> null          // Checking / Downloading / ReadyToInstall
        }
        if (message != null) {
            manualCheck = false
            updateMessage = message
        }
    }

    // Touchpad zaberie celu obrazovku; spat sa ide krizikom alebo gestom spat.
    // Ked sa PC medzitym strati, touchpad sa zavrie sam — nema kam posielat.
    val server = uiState.discovery as? DiscoveryState.Found
    if (showTouchpad && server != null) {
        TouchpadScreen(server.ip, server.port, onZavriet = { showTouchpad = false })
        return
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            // Android 15 kresli appku (targetSdk 35) aj pod stavovy riadok —
            // hlavicka by bola pod hodinami a koliecko by sa nedalo stlacit.
            // Na starsich Androidoch su tieto okraje nulove.
            .systemBarsPadding()
            // Vodorovne 12dp, zvisle 8dp: kazdy usetreny bod hore aj dole je
            // dalsi kus playlistu, ktory sa na obrazovku zmesti.
            .padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // ── top bar: status + power ───────────────────────────────────────────
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusChip(
                discovery = uiState.discovery,
                isPlaying = uiState.playback is PlaybackState.Playing,
                isConnecting = uiState.playback is PlaybackState.Connecting,
                isError = uiState.playback is PlaybackState.Error,
                streamingActive = uiState.streamingActive,
            )
            // The menu is always available: the NAS is independent of the PC,
            // so update settings must be reachable with the PC switched off.
            Row(verticalAlignment = Alignment.CenterVertically) {
            // Ozubene koliecko je na tom istom mieste ako vo vsetkych ostatnych
            // appkach (docs/shared-standard.md 2.6). Do 20. 8. 2026 sa nastavenia v tejto
            // appke skryvali pod ⋮, inde boli text alebo tlacidlo — a clovek
            // ich v kazdej hladal inde. V ⋮ ostava len to, co je vlastne tejto
            // appke (uspatie a vypnutie PC).
            // Vlastna akcia appky (docs/shared-standard.md 2.6): telefon ako touchpad pre PC.
            if (isFound) {
                IconButton(
                    onClick = { showTouchpad = true },
                    modifier = Modifier.size(36.dp),
                ) {
                    Icon(MysIcon, contentDescription = "Touchpad pre PC")
                }
            }
            IconButton(
                onClick = { showUpdateSettings = true },
                modifier = Modifier.size(36.dp),
            ) {
                Icon(Icons.Filled.Settings, contentDescription = "Nastavenia")
            }
            Box {
                IconButton(
                    onClick = { menuExpanded = true },
                    modifier = Modifier.size(36.dp),
                ) {
                    Icon(Icons.Filled.MoreVert, contentDescription = "Možnosti")
                }
                DropdownMenu(
                    expanded = menuExpanded,
                    onDismissRequest = { menuExpanded = false },
                ) {
                    if (isFound) {
                        DropdownMenuItem(
                            text = { Text("Spánok 2") },
                            onClick = {
                                menuExpanded = false
                                pendingPowerAction = "sleep2"
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Uspať PC") },
                            onClick = {
                                menuExpanded = false
                                pendingPowerAction = "sleep"
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Vypnúť PC", color = MaterialTheme.colorScheme.error) },
                            onClick = {
                                menuExpanded = false
                                pendingPowerAction = "shutdown"
                            },
                        )
                        HorizontalDivider()
                    }
                    // Verzia sa NEUKAZUJE tu — má jedno miesto, pätičku dole
                    // (docs/shared-standard.md 2.6). Dve miesta znamenajú, že sa raz
                    // rozídu.
                    DropdownMenuItem(
                        text = { Text("Skontrolovať teraz") },
                        onClick = {
                            menuExpanded = false
                            manualCheck = true
                            onCheckUpdates()
                        },
                    )
                    // "Ukoncit" tu NIE JE: je vidno priamo na obrazovke,
                    // vpravo vedla tlacidla streamingu. Dve miesta pre ten isty
                    // ukon su o jedno viac, nez treba.
                }
            }
            }
        }

        Spacer(Modifier.height(6.dp))

        // Hľadanie servera beží dokola: NotFound → Discovering → NotFound každých
        // ~15 s. Keby sa obrazovka riadila priamo týmto stavom, striedala by sa
        // celostránková točiaca sa kolieska s hláškou o nedostupnom serveri a
        // tlačidlo Reconnect by spod prsta miznulo. Preto: len PRVÉ hľadanie
        // ukáže kolieso, potom už panel ostáva a mení sa v ňom jediný riadok.
        var everFailed by rememberSaveable { mutableStateOf(false) }
        LaunchedEffect(uiState.discovery) {
            if (uiState.discovery is DiscoveryState.NotFound) everFailed = true
        }

        when {
            uiState.discovery is DiscoveryState.Found -> Unit   // rieši vetva nižšie
            everFailed -> CenteredInfo(weightBox = true) {
                Text("Server nedostupný", color = MaterialTheme.colorScheme.error)
                Spacer(Modifier.height(8.dp))
                Text(
                    text = if (uiState.discovery is DiscoveryState.Discovering) {
                        "Hľadám ďalej…"
                    } else {
                        "Skúsim to znova o chvíľu."
                    },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                Button(onClick = onReconnectClicked) { Text("Skúsiť hneď") }
                Spacer(Modifier.height(16.dp))
                // Toto je celý zmysel: aj s vypnutým PC sa dá appka
                // aktualizovať, lebo APK je na NAS-e, nie na PC. Bez tejto
                // vety to z obrazovky nikto neuhádne.
                Text(
                    "Aktualizácia appky funguje aj teraz — je v ponuke ⋮ hore " +
                        "vpravo (APK je na NAS-e, nie na PC).",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }

            else -> CenteredInfo(weightBox = true) {
                CircularProgressIndicator(modifier = Modifier.size(40.dp))
                Spacer(Modifier.height(12.dp))
                Text("Hľadám server...", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }

        when (uiState.discovery) {
            is DiscoveryState.Discovering, is DiscoveryState.NotFound -> Unit

            is DiscoveryState.Found -> {
                // Kapela NAD nazvom skladby a vacsim pismom.
                //
                // Skusali sme ich (1. 9. 2026) dat vedla seba na jeden riadok,
                // aby sa vyuzilo volne miesto po stranach — v praxi to bolo
                // horsie: dlhsie mena sa zacali orezavat a dvojica roznych
                // velkosti na jednej ciare posobila neusporiadane. Usetreny
                // riadok za to nestal, cas sa presunul k ovladacim tlacidlam.
                //
                // `lineHeight` je nastavena vyslovne: predvolena je zhruba
                // 1,4-nasobok pisma a na dvoch riadkoch nad sebou z toho vznikne
                // medzera, ktora tu nie je na nic. Je v `sp`, takze skalovanie
                // pisma z Nastaveni na nu plati rovnako ako na text.
                Spacer(Modifier.height(6.dp))
                if (uiState.nowPlaying.artist.isNotEmpty()) {
                    Text(
                        text = uiState.nowPlaying.artist,
                        fontSize = 26.sp,
                        lineHeight = 30.sp,
                        fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.height(2.dp))
                }
                Text(
                    text = uiState.nowPlaying.title.ifEmpty { "—" },
                    fontSize = 16.sp,
                    lineHeight = 19.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )

                // Poloha pocas tahania posuvnika; null = netaha sa a plati
                // to, co hlasi server.
                var scrubMs by remember { mutableStateOf<Long?>(null) }

                Spacer(Modifier.height(10.dp))
                SeekBar(
                    positionMs = uiState.nowPlaying.positionMs,
                    durationMs = uiState.nowPlaying.durationMs,
                    onSeek = onSeek,
                    onScrub = { scrubMs = it },
                )

                Spacer(Modifier.height(6.dp))
                TransportRow(
                    isPlaying = uiState.nowPlaying.state == "playing",
                    positionMs = scrubMs ?: uiState.nowPlaying.positionMs,
                    durationMs = uiState.nowPlaying.durationMs,
                    onPrev = onPrev,
                    onPlayPause = onPlayPause,
                    onNext = onNext,
                    onStop = onStop,
                )

                Spacer(Modifier.height(2.dp))
                VolumeBar(
                    volume = uiState.nowPlaying.volume,
                    onVolume = onVolume,
                    onToggleMute = onToggleMute,
                )

                // Streaming a "Ukoncit" v jednom riadku (1. 9. 2026).
                // "Ukoncit" bolo predtym samostatne tlacidlo dole a stalo cely
                // riadok (48dp); tu sa zvezie v riadku, ktory na obrazovke uz
                // aj tak je, takze naspat na ocich nic nestoji.
                Spacer(Modifier.height(6.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    ListeningToggle(
                        listening = uiState.listening,
                        serverStreaming = uiState.streamingActive,
                        onToggle = onToggleListening,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    TextButton(
                        onClick = onExitClicked,
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                    ) {
                        Text("Ukončiť", color = MaterialTheme.colorScheme.outline)
                    }
                }

                Spacer(Modifier.height(8.dp))
                val listState = rememberLazyListState()
                val currentIndex = uiState.nowPlaying.currentIndex
                var query by rememberSaveable { mutableStateOf("") }
                val shown = remember(uiState.playlist, query) {
                    PlaylistFilter.filter(uiState.playlist, query)
                }

                PlaylistSearchField(
                    query = query,
                    onQueryChange = { query = it },
                    shownCount = shown.size,
                    totalCount = uiState.playlist.size,
                )

                Spacer(Modifier.height(6.dp))

                // Auto-scroll na hrajúcu skladbu. Počas hľadania sa VYPÍNA —
                // inak by skok na hrajúcu pieseň odtiahol zoznam spod prsta
                // presne vo chvíli, keď v ňom používateľ niečo hľadá.
                LaunchedEffect(currentIndex, uiState.playlist.size, query) {
                    if (query.isNotBlank()) return@LaunchedEffect
                    val pos = shown.indexOfFirst { it.index == currentIndex }
                    if (pos >= 0) listState.animateScrollToItem(pos)
                }

                if (shown.isEmpty()) {
                    CenteredInfo(weightBox = true) {
                        Text(
                            "Nič nesedí na: $query",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    // Posuvník je VĽAVO zámerne: pravý okraj je pri držaní
                    // telefónu pod palcom a zoznam sa tam otvára na ťuknutie.
                    Row(modifier = Modifier.weight(1f).fillMaxWidth()) {
                        FastScrollbar(
                            listState = listState,
                            itemCount = shown.size,
                            modifier = Modifier.fillMaxHeight(),
                        )
                        LazyColumn(
                            state = listState,
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                        ) {
                            items(shown, key = { it.index }) { item ->
                                PlaylistRow(
                                    item = item,
                                    isCurrent = item.index == currentIndex,
                                    isPlaying = uiState.nowPlaying.state == "playing",
                                    onClick = { onPlayIndex(item.index) },
                                )
                            }
                        }
                    }
                }
            }
        }

        // Pod playlistom uz nie je nic okrem paticky. Paticka sama sa
        // NEZMENSUJE: jej rozmery (11sp, padding 16/10) su spolocne pre vsetky
        // appky podla docs/shared-standard.md 2.6 a menili by sa vo vsetkych naraz.

        // Pätička s verziou — úplne dole, rovnaká vo všetkých appkách
        // (docs/shared-standard.md 2.6). Ťuknutie spustí ručnú kontrolu.
        VersionFooter(
            remote = uiState.remoteVersion,
            newer = uiState.updateState is UpdateState.Available,
            onClick = {
                manualCheck = true
                onCheckUpdates()
            },
        )
    }

    pendingPowerAction?.let { action ->
        val isShutdown = action == "shutdown"
        val title = when (action) {
            "shutdown" -> "Vypnúť PC?"
            "sleep2" -> "Pustiť Spánok 2?"
            else -> "Uspať PC?"
        }
        val body = when (action) {
            "shutdown" -> "Naozaj okamžite vypnúť počítač?"
            // Zoznam skladieb aj to, ci sa playlist po dohrati vrati do
            // povodneho stavu, sa nastavuje v prehravaci na PC — telefon
            // len povie „teraz".
            "sleep2" -> "Prehrávač pridá na koniec playlistu skladby zo zoznamu " +
                "Spánok 2 a hneď ich pustí. Po dohratí sa PC uspí alebo vypne " +
                "podľa nastavenia v prehrávači."
            else -> "Naozaj uspať počítač?"
        }
        val confirmLabel = when (action) {
            "shutdown" -> "Áno, vypnúť"
            "sleep2" -> "Áno, pustiť"
            else -> "Áno, uspať"
        }
        AlertDialog(
            onDismissRequest = { pendingPowerAction = null },
            title = { Text(title) },
            text = { Text(body) },
            confirmButton = {
                TextButton(onClick = {
                    pendingPowerAction = null
                    when (action) {
                        "shutdown" -> onShutdown()
                        "sleep2" -> onSleep2()
                        else -> onSleep()
                    }
                }) {
                    Text(
                        confirmLabel,
                        color = if (isShutdown) MaterialTheme.colorScheme.error
                        else MaterialTheme.colorScheme.primary,
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingPowerAction = null }) { Text("Zrušiť") }
            },
        )
    }

    // Nová verzia na NAS-e, ešte nestiahnutá. Rovnaké znenie aj poradie
    // tlačidiel ako vo všetkých ostatných appkách (docs/shared-standard.md 2.4) — sťahuje
    // sa (~50 MB) až po klepnutí na „Nainštalovať".
    (uiState.updateState as? UpdateState.Available)?.let { avail ->
        AlertDialog(
            onDismissRequest = onDismissUpdate,
            title = { Text("Nová verzia") },
            text = {
                Column {
                    Text(
                        "Na NAS-e je verzia ${avail.manifest.versionName} " +
                            "(${avail.manifest.versionCode}), máš ${uiState.appVersion}. " +
                            "Nainštalovať teraz?"
                    )
                    if (avail.manifest.notes.isNotBlank()) {
                        Spacer(Modifier.height(8.dp))
                        Text(
                            avail.manifest.notes,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = onConfirmUpdate) { Text("Nainštalovať") }
            },
            dismissButton = {
                TextButton(onClick = onDismissUpdate) { Text("Neskôr") }
            },
        )
    }

    // Stiahnuté a overené (SHA-256) — ostáva odovzdať to systémovému inštalátoru.
    (uiState.updateState as? UpdateState.ReadyToInstall)?.let { ready ->
        AlertDialog(
            onDismissRequest = onDismissUpdate,
            title = { Text("Nová verzia") },
            text = { Text("Verzia ${ready.manifest.versionName} je stiahnutá a pripravená.") },
            confirmButton = {
                TextButton(onClick = onInstallUpdate) { Text("Nainštalovať") }
            },
            dismissButton = {
                TextButton(onClick = onDismissUpdate) { Text("Neskôr") }
            },
        )
    }

    updateMessage?.let { message ->
        AlertDialog(
            onDismissRequest = { updateMessage = null },
            title = { Text("Aktualizácie") },
            text = { Text(message) },
            confirmButton = {
                TextButton(onClick = { updateMessage = null }) { Text("OK") }
            },
        )
    }

    if (showUpdateSettings) {
        NastaveniaDialog(
            initial = uiState.updateConfig,
            manualIp = uiState.manualServerIp,
            manualPort = uiState.manualServerPort,
            onSaveManualServer = onSaveManualServer,
            onSave = onSaveUpdateSettings,
            onTest = onTestConnection,
            onDismiss = { showUpdateSettings = false },
        )
    }
}

/**
 * Vzhlad: rezim a velkost pisma. Sekcia je vo vsetkych appkach rovnaka
 * (docs/shared-standard.md 2.8), tu je postavena v Compose.
 *
 * Po zmene sa aktivita stavia NANOVO. Velkost pisma sedi v konfiguracii
 * kontextu, ktory vznikol pri `attachBaseContext` — uz vykreslena obrazovka
 * o zmene nema ako vediet. Appka ma jedinu aktivitu, takze `recreate()`
 * prekresli aj tento dialog.
 */
@Composable
private fun VzhladSekcia() {
    val ctx = LocalContext.current
    var rezim by remember { mutableStateOf(Vzhlad.rezim(ctx)) }
    var pismo by remember { mutableStateOf(Vzhlad.pismo(ctx)) }
    var pismoWidgetu by remember { mutableStateOf(Vzhlad.pismoWidgetu(ctx)) }

    fun uloz(novyRezim: Int, novePismo: Int, noveWidget: Int = pismoWidgetu) {
        rezim = novyRezim
        pismo = novePismo
        pismoWidgetu = noveWidget
        Vzhlad.uloz(ctx, novyRezim, novePismo, noveWidget)
        OvladacWidgetProvider.prekresliVsetky(ctx)
        (ctx as? Activity)?.recreate()
    }

    Text("Vzhľad", style = MaterialTheme.typography.titleSmall)
    Spacer(Modifier.height(4.dp))
    Text(
        "Prehrávač je tmavý od začiatku. Čierny režim ide ešte o krok ďalej: " +
            "pozadie je čisto čierne, takže sa na OLED displeji vôbec nerozsvieti " +
            "a šetrí batériu. Platí aj pre widget na ploche. Veľkosť písma sa " +
            "pripočítava k tomu, čo máš nastavené v systéme; widget má vlastnú, " +
            "lebo sa číta z inej vzdialenosti.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    listOf(
        Vzhlad.PODLA_SYSTEMU to "Podľa systému",
        Vzhlad.SVETLY to "Základný (tmavý)",
        Vzhlad.CIERNY to "Čierny (šetrí batériu)",
    ).forEach { (hodnota, popis) ->
        Row(verticalAlignment = Alignment.CenterVertically) {
            RadioButton(selected = rezim == hodnota, onClick = { uloz(hodnota, pismo) })
            Text(popis, style = MaterialTheme.typography.bodyMedium)
        }
    }
    Spacer(Modifier.height(8.dp))
    Text("Veľkosť písma", style = MaterialTheme.typography.titleSmall)
    KrokPisma(pismo) { uloz(rezim, it) }
    Spacer(Modifier.height(8.dp))
    // Widget ma VLASTNU velkost pisma (29. 8. 2026): na ploche je to jeden
    // riadok medzi ikonami a cita sa z inej vzdialenosti nez obrazovka appky.
    Text("Veľkosť písma vo widgete", style = MaterialTheme.typography.titleSmall)
    KrokPisma(pismoWidgetu) { uloz(rezim, pismo, it) }
}

/** Prenesene data — Wi-Fi zvlast, mobilne zvlast. Texty pyta [Prenos]. */
@Composable
private fun PrenosSekcia() {
    val context = LocalContext.current
    var text by remember { mutableStateOf(Prenos.popis(context)) }
    Text(Prenos.NADPIS, style = MaterialTheme.typography.titleSmall)
    Spacer(Modifier.height(4.dp))
    Text(text, style = MaterialTheme.typography.bodyMedium)
    Spacer(Modifier.height(4.dp))
    Text(
        Prenos.POZNAMKA,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.height(8.dp))
    OutlinedButton(onClick = {
        Prenos.vynuluj(context)
        text = Prenos.popis(context)
    }) { Text(Prenos.VYNULOVAT) }
}

/** Rad − / popis / + na jeden krok pisma. Rovnaky tvar pre appku aj widget. */
@Composable
private fun KrokPisma(krok: Int, onZmena: (Int) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedButton(
            onClick = { onZmena((krok - 1).coerceAtLeast(Vzhlad.PISMO_MIN)) },
            enabled = krok > Vzhlad.PISMO_MIN,
        ) { Text("−") }
        Spacer(Modifier.width(12.dp))
        Text(
            // Popis kroku pyta Vzhlad — rozsah sa 3. 9. 2026 rozsiril na
            // -6..+6 a natvrdo napisane "mensie o 1" by pri -4 klamalo.
            text = Vzhlad.nazovKroku(krok),
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.width(12.dp))
        OutlinedButton(
            onClick = { onZmena((krok + 1).coerceAtMost(Vzhlad.PISMO_MAX)) },
            enabled = krok < Vzhlad.PISMO_MAX,
        ) { Text("+") }
    }
}

/**
 * Nastavenia appky. Dve sekcie: **server hudby** a **aktualizacie z NAS-u**.
 *
 * Do 27. 8. 2026 tu bola len druha sekcia a dialog sa volal "Nastavenia
 * aktualizacii" — kto hladal, kde sa zadava adresa prehravaca, nenasiel nic
 * a musel verit, ze si ju appka najde sama. Ked si ju nenajde (Tailscale,
 * hostovska Wi-Fi, router bez broadcastu), nemal co spravit.
 */
@Composable
private fun NastaveniaDialog(
    initial: UpdateConfig,
    manualIp: String,
    manualPort: Int,
    onSaveManualServer: (String, Int) -> Unit,
    onSave: (UpdateConfig) -> Unit,
    onTest: suspend (UpdateConfig) -> String,
    onDismiss: () -> Unit,
) {
    var serverIp by remember { mutableStateOf(manualIp) }
    var serverPort by remember { mutableStateOf(if (manualPort > 0) manualPort.toString() else "") }
    var host by remember { mutableStateOf(initial.host) }
    var share by remember { mutableStateOf(initial.share) }
    var folder by remember { mutableStateOf(initial.folder) }
    var user by remember { mutableStateOf(initial.username) }
    var pass by remember { mutableStateOf(initial.password) }
    var passVisible by remember { mutableStateOf(false) }
    var testResult by remember { mutableStateOf<String?>(null) }
    var testing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    // Trimmed here so "Otestovať spojenie" exercises exactly what gets saved —
    // an invisible trailing space must not make the test and the real check
    // behave differently. The password is left alone; spaces can be part of it.
    val current = UpdateConfig(host.trim(), share.trim(), folder.trim(), user.trim(), pass)

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Nastavenia") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                // autoCorrect off everywhere: the keyboard silently "fixing"
                // a hostname or username looks exactly like a wrong password.
                val plainField = KeyboardOptions(
                    keyboardType = KeyboardType.Ascii, autoCorrect = false,
                )
                // ── 1. vzhľad ──────────────────────────────────────────
                // Vzhľad je nastavenie APPKY, takže patrí pred servery
                // (docs/shared-standard.md 2.8). Sekcia je vo všetkých appkách rovnaká.
                VzhladSekcia()

                Spacer(Modifier.height(16.dp))
                HorizontalDivider()
                Spacer(Modifier.height(16.dp))

                // ── 2. server hudby ─────────────────────────────────────
                Text(
                    "Server hudby (prehrávač na počítači)",
                    style = MaterialTheme.typography.titleSmall,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "Prehrávač na počítači sa sám hlási do siete a appka si ho nájde " +
                        "bez zadávania čohukoľvek. Meno ani heslo nemá — kto je v tej istej " +
                        "sieti, ovláda ho. Adresu tu vyplň len vtedy, keď sa nenájde: cez " +
                        "Tailscale, na hosťovskej Wi-Fi a na routeroch, ktoré blokujú " +
                        "broadcast, sa jeho ohlásenie nedostane. Prázdne = hľadaj sám.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    serverIp, { serverIp = it },
                    label = { Text("IP počítača (nepovinné)") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Ascii, autoCorrect = false,
                    ),
                    supportingText = { Text("Napr. 192.168.1.50 alebo Tailscale IP") },
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    serverPort, { serverPort = it.filter { c -> c.isDigit() } },
                    label = { Text("Port") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    supportingText = { Text("Prázdne = 8765, teda predvolba prehrávača") },
                )

                Spacer(Modifier.height(16.dp))
                HorizontalDivider()
                Spacer(Modifier.height(16.dp))

                // ── 3. prenesené dáta ──────────────────────────────────────
                // Nadpis, text aj tlačidlo pýta Prenos: sekcia je vo všetkých
                // appkách rovnaká. Tu má zmysel preto, že appka sa pýta
                // prehrávača na stav každú sekundu — cez Tailscale mimo domu
                // idú tie dopyty cez mobilné dáta.
                PrenosSekcia()

                Spacer(Modifier.height(16.dp))
                HorizontalDivider()
                Spacer(Modifier.height(16.dp))

                // ── 4. aktualizácie z NAS-u ────────────────────────────────
                Text(
                    "Aktualizácie appky (NAS)",
                    style = MaterialTheme.typography.titleSmall,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "Odtiaľto si appka sťahuje vlastné nové verzie. Je to zdieľaný " +
                        "priečinok na NAS-e (SMB) — s hudbou to nemá nič spoločné a heslo " +
                        "je k NAS-u, nie k prehrávaču.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                // Popisky aj poradie sú rovnaké vo všetkých appkách
                // (docs/shared-standard.md 2.6) — kto ich raz vyplnil v jednej, nájde
                // ich v druhej na tom istom mieste.
                OutlinedTextField(
                    host, { host = it },
                    label = { Text("Adresa NAS-u") }, singleLine = true,
                    keyboardOptions = plainField,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    share, { share = it },
                    label = { Text("Zdieľaný priečinok") }, singleLine = true,
                    keyboardOptions = plainField,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    folder, { folder = it },
                    label = { Text("Podpriečinok appky") }, singleLine = true,
                    keyboardOptions = plainField,
                    supportingText = { Text("Prázdne = koreň sharu") },
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    user, { user = it },
                    label = { Text("SMB meno") }, singleLine = true,
                    keyboardOptions = plainField,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    pass, { pass = it },
                    label = { Text("SMB heslo") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    visualTransformation = if (passVisible) VisualTransformation.None
                    else PasswordVisualTransformation(),
                    trailingIcon = {
                        IconButton(onClick = { passVisible = !passVisible }) {
                            Icon(
                                if (passVisible) EyeOffIcon else EyeIcon,
                                contentDescription = if (passVisible) "Skryť heslo"
                                else "Zobraziť heslo",
                            )
                        }
                    },
                )
                Spacer(Modifier.height(12.dp))
                TextButton(
                    enabled = !testing && current.isComplete,
                    onClick = {
                        testing = true
                        testResult = null
                        scope.launch {
                            testResult = onTest(current)
                            testing = false
                        }
                    },
                ) { Text(if (testing) "Skúšam..." else "Otestovať spojenie") }
                testResult?.let {
                    Spacer(Modifier.height(4.dp))
                    Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                onSaveManualServer(serverIp.trim(), serverPort.toIntOrNull() ?: 0)
                onSave(current)
                onDismiss()
            }) { Text("Uložiť") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Zrušiť") }
        },
    )
}

// Material "visibility" glyphs, inlined — pulling in material-icons-extended
// for two icons would grow the APK noticeably (release is not minified).
private fun eyeVector(name: String, pathData: String): ImageVector =
    ImageVector.Builder(
        name = name,
        defaultWidth = 24.dp, defaultHeight = 24.dp,
        viewportWidth = 24f, viewportHeight = 24f,
    ).addPath(
        pathData = addPathNodes(pathData),
        fill = SolidColor(Color.White),   // overridden by Icon's tint
    ).build()

// Material "mouse" glyph.
private val MysIcon by lazy {
    eyeVector(
        "Mouse",
        "M13,1.07V9h7c0,-4.08 -3.05,-7.44 -7,-7.93zM4,15c0,4.42 3.58,8 8,8s8,-3.58 8,-8v-4H4v4z" +
            "m7,-13.93C7.05,1.56 4,4.92 4,9h7V1.07z",
    )
}

private val EyeIcon by lazy {
    eyeVector(
        "Visibility",
        "M12,4.5C7,4.5 2.73,7.61 1,12c1.73,4.39 6,7.5 11,7.5s9.27,-3.11 11,-7.5c-1.73,-4.39 " +
            "-6,-7.5 -11,-7.5zM12,17c-2.76,0 -5,-2.24 -5,-5s2.24,-5 5,-5 5,2.24 5,5 -2.24,5 " +
            "-5,5zM12,9c-1.66,0 -3,1.34 -3,3s1.34,3 3,3 3,-1.34 3,-3 -1.34,-3 -3,-3z",
    )
}

private val EyeOffIcon by lazy {
    eyeVector(
        "VisibilityOff",
        "M12,7c2.76,0 5,2.24 5,5 0,0.65 -0.13,1.26 -0.36,1.83l2.92,2.92c1.51,-1.26 2.7,-2.89 " +
            "3.43,-4.75 -1.73,-4.39 -6,-7.5 -11,-7.5 -1.4,0 -2.74,0.25 -3.98,0.7l2.16,2.16C10.74," +
            "7.13 11.35,7 12,7zM2,4.27l2.28,2.28 0.46,0.46C3.08,8.3 1.78,10.02 1,12c1.73,4.39 6," +
            "7.5 11,7.5 1.55,0 3.03,-0.3 4.38,-0.84l0.42,0.42L19.73,22 21,20.73 3.27,3 2,4.27zM7.53," +
            "9.8l1.55,1.55c-0.05,0.21 -0.08,0.43 -0.08,0.65 0,1.66 1.34,3 3,3 0.22,0 0.44,-0.03 " +
            "0.65,-0.08l1.55,1.55c-0.67,0.33 -1.41,0.53 -2.2,0.53 -2.76,0 -5,-2.24 -5,-5 0,-0.79 " +
            "0.2,-1.53 0.53,-2.2zM11.84,9.02l3.15,3.15 0.02,-0.16c0,-1.66 -1.34,-3 -3,-3l-0.17,0.01z",
    )
}

@Composable
private fun ColumnScope.CenteredInfo(weightBox: Boolean, content: @Composable ColumnScope.() -> Unit) {
    Box(
        modifier = if (weightBox) Modifier.weight(1f).fillMaxWidth() else Modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, content = content)
    }
}

@Composable
private fun SeekBar(
    positionMs: Long,
    durationMs: Long,
    onSeek: (Long) -> Unit,
    onScrub: (Long?) -> Unit,
) {
    var dragging by remember { mutableStateOf(false) }
    var dragValue by remember { mutableStateOf(0f) }
    val dur = durationMs.coerceAtLeast(1L).toFloat()
    val pos = (if (dragging) dragValue else positionMs.toFloat()).coerceIn(0f, dur)

    // Cas tu UZ NIE JE — presunul sa do riadku s ovladacimi tlacidlami
    // (TransportRow), kde po stranach ostavalo prazdne miesto. Samostatny
    // riadok pre dva kratke udaje bol cely riadok navyse.
    //
    // 36dp namiesto predvolenych 48dp: predvolena vyska je dotykovy ciel,
    // nie kreslena ciara — palec 36dp na tahanie stale pohodlne trafi
    // a jazdec (20dp) sa do nej zmesti bez orezania.
    Slider(
        value = pos,
        // `onScrub` posiela tahanu polohu von: cas sa kresli v inom riadku
        // (TransportRow) a bez tohto by pocas tahania stal na hodnote zo
        // servera — clovek by tahal naslepo a nevidel, kam mieri.
        onValueChange = {
            dragging = true
            dragValue = it
            onScrub(it.toLong())
        },
        onValueChangeFinished = {
            dragging = false
            onScrub(null)
            onSeek(dragValue.toLong())
        },
        valueRange = 0f..dur,
        enabled = durationMs > 0,
        modifier = Modifier.fillMaxWidth().height(36.dp),
    )
}

@Composable
private fun ListeningToggle(
    listening: Boolean,
    serverStreaming: Boolean,
    onToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // The app starts as a pure remote; receiving audio on the phone is opt-in.
    //
    // Sirku uz neurcuje tlacidlo samo (bolo `fillMaxWidth`), ale volajuci:
    // vedla neho sedi "Ukoncit" a to potrebuje svoj kus riadku.
    FilledTonalButton(
        onClick = onToggle,
        enabled = listening || serverStreaming,
        modifier = modifier,
    ) {
        Text(
            when {
                listening -> "⏹  Vypnúť streaming"
                serverStreaming -> "🎧  Streaming"
                else -> "🎧  Streaming nedostupný"
            }
        )
    }
}

@Composable
private fun VolumeBar(volume: Int, onVolume: (Int) -> Unit, onToggleMute: () -> Unit) {
    var dragging by remember { mutableStateOf(false) }
    var dragValue by remember { mutableStateOf(0f) }
    val vol = (if (dragging) dragValue else volume.toFloat()).coerceIn(0f, 100f)

    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onToggleMute, modifier = Modifier.size(36.dp)) {
            // Trojstavová ikonka ako vo Windows: 🔇 / 🔉 / 🔊
            Text(
                when {
                    vol.toInt() == 0 -> "🔇"
                    vol < 50f -> "🔉"
                    else -> "🔊"
                },
                fontSize = 16.sp,
            )
        }
        Spacer(Modifier.width(4.dp))
        Slider(
            value = vol,
            onValueChange = { dragging = true; dragValue = it },
            onValueChangeFinished = {
                dragging = false
                onVolume(dragValue.toInt())
            },
            valueRange = 0f..100f,
            modifier = Modifier.weight(1f),
        )
        Spacer(Modifier.width(8.dp))
        Text(
            "${vol.toInt()}",
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(30.dp),
            textAlign = TextAlign.End,
        )
    }
}

@Composable
private fun TransportRow(
    isPlaying: Boolean,
    positionMs: Long,
    durationMs: Long,
    onPrev: () -> Unit,
    onPlayPause: () -> Unit,
    onNext: () -> Unit,
    onStop: () -> Unit,
) {
    // Rovnaké poradie ako vo Windows appke: ⏮ ▶ ⏹ ⏭
    //
    // Po stranach tohto riadku ostavalo prazdne miesto, kym cas mal pod
    // posuvnikom vlastny riadok. Teraz sedi tu: uplynuty cas vlavo, dlzka
    // vpravo, tlacidla medzi nimi.
    //
    // Casy maju PEVNU sirku: bez nej by sa tlacidla posunuli vzdy, ked cas
    // preskoci z 9:59 na 10:00 alebo ked skladba trva cez hodinu — a palec
    // by uz nesiel po pamati na to iste miesto.
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            formatTime(positionMs),
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(44.dp),
        )
        Row(
            modifier = Modifier.weight(1f),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            GlyphButton("⏮", onPrev)
            GlyphButton(if (isPlaying) "⏸" else "▶", onPlayPause, big = true)
            GlyphButton("⏹", onStop)
            GlyphButton("⏭", onNext)
        }
        Text(
            formatTime(durationMs),
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.End,
            modifier = Modifier.width(44.dp),
        )
    }
}

@Composable
private fun GlyphButton(glyph: String, onClick: () -> Unit, big: Boolean = false) {
    // Vzhľad tlačidla ako vo Windows appke: výplň, svetlejší rámik, zaoblenie.
    Box(
        modifier = Modifier
            .size(
                width = if (big) 76.dp else 60.dp,
                height = if (big) 52.dp else 46.dp,
            )
            .clip(RoundedCornerShape(6.dp))
            .background(MetalButton)
            .border(1.dp, MetalButtonBorder, RoundedCornerShape(6.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            glyph,
            fontSize = if (big) 24.sp else 19.sp,
            color = MetalTextPrimary,
        )
    }
}

/**
 * Hľadanie v playliste.
 *
 * Existuje preto, že pri dlhom playliste trvá doscrollovať sa kamsi večnosť —
 * a to je aj dôvod, prečo je vedľa neho posuvník. Počítadlo „N z M" je
 * dôležitejšie, než vyzerá: bez neho sa prázdny výsledok nedá odlíšiť od
 * playlistu, ktorý sa ešte nenačítal.
 */
@Composable
private fun PlaylistSearchField(
    query: String,
    onQueryChange: (String) -> Unit,
    shownCount: Int,
    totalCount: Int,
) {
    OutlinedTextField(
        value = query,
        onValueChange = onQueryChange,
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        placeholder = { Text("Hľadať v playliste…") },
        leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
        trailingIcon = {
            if (query.isNotEmpty()) {
                IconButton(onClick = { onQueryChange("") }) {
                    Icon(Icons.Filled.Clear, contentDescription = "Zrušiť hľadanie")
                }
            }
        },
        supportingText = if (query.isBlank()) null else {
            { Text("$shownCount z $totalCount skladieb") }
        },
    )
}

/**
 * Posuvník vedľa playlistu — ťahaním sa preskočí kamkoľvek v zozname.
 *
 * Compose nemá vstavaný „fast scroller", a bez neho sa v playliste o tisícoch
 * skladieb inak než scrollovaním pohnúť nedá. Bežec (thumb) je vysoký podľa
 * toho, akú časť zoznamu vidno — pri dlhom playliste je malý a rovno tým
 * ukazuje, koľko ho ešte je.
 *
 * Ťuknutie kamkoľvek na dráhu skočí na dané miesto; ťahanie posúva plynulo.
 * Oboje používa `scrollToItem` (bez animácie) — animovaný skok počas ťahania
 * vyzerá ako zasekávanie, lebo dobieha prst.
 */
@Composable
private fun FastScrollbar(
    listState: LazyListState,
    itemCount: Int,
    modifier: Modifier = Modifier,
) {
    if (itemCount <= 1) {
        // Prázdny zoznam alebo jediná skladba — posuvník by nemal čo posúvať
        // a len by ukrojil šírku z názvov.
        Spacer(modifier.width(0.dp))
        return
    }
    val scope = rememberCoroutineScope()
    val density = LocalDensity.current
    var trackPx by remember { mutableStateOf(0f) }

    /** Kam sa má zoznam presunúť, keď je prst na `y` pixeloch dráhy. */
    fun scrollTo(y: Float) {
        if (trackPx <= 0f) return
        val fraction = (y / trackPx).coerceIn(0f, 1f)
        val target = (fraction * (itemCount - 1)).toInt().coerceIn(0, itemCount - 1)
        scope.launch { listState.scrollToItem(target) }
    }

    val visible = listState.layoutInfo.visibleItemsInfo.size.coerceAtLeast(1)
    val first = listState.firstVisibleItemIndex
    // Podiel zoznamu, ktorý je vidno — z neho výška bežca.
    val thumbFraction = (visible.toFloat() / itemCount).coerceIn(0.06f, 1f)
    val maxFirst = (itemCount - visible).coerceAtLeast(1)
    val posFraction = (first.toFloat() / maxFirst).coerceIn(0f, 1f)

    Box(
        modifier = modifier
            .width(20.dp)
            .padding(end = 6.dp)
            .onSizeChanged { trackPx = it.height.toFloat() }
            .pointerInput(itemCount) {
                detectTapGestures { offset -> scrollTo(offset.y) }
            }
            .pointerInput(itemCount) {
                detectVerticalDragGestures { change, _ ->
                    change.consume()
                    scrollTo(change.position.y)
                }
            },
    ) {
        // dráha
        Box(
            modifier = Modifier
                .fillMaxHeight()
                .width(4.dp)
                .align(Alignment.Center)
                .clip(RoundedCornerShape(2.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
        )
        // bežec
        val trackDp = with(density) { trackPx.toDp() }
        val thumbDp = trackDp * thumbFraction
        Box(
            modifier = Modifier
                .offset(y = (trackDp - thumbDp) * posFraction)
                .height(thumbDp)
                .width(8.dp)
                .align(Alignment.TopCenter)
                .clip(RoundedCornerShape(4.dp))
                .background(MaterialTheme.colorScheme.primary),
        )
    }
}

@Composable
private fun PlaylistRow(
    item: PlaylistItem,
    isCurrent: Boolean,
    isPlaying: Boolean,
    onClick: () -> Unit,
) {
    // Hrajúci riadok = štýl vybraného riadku vo Windows playliste:
    // jantárové pozadie, tmavý text.
    val currentFg = MaterialTheme.colorScheme.onPrimary
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .background(
                if (isCurrent) MaterialTheme.colorScheme.primary else Color.Transparent
            )
            // Zvisle 3dp namiesto 10dp (1. 9. 2026). Riadok je hlavny zdroj
            // usetreneho miesta: v zozname ich su desiatky, takze kazdy bod tu
            // sa nasobi, kym medzera nad zoznamom sa usetri iba raz.
            .padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.width(24.dp), contentAlignment = Alignment.Center) {
            if (isCurrent) {
                Text(
                    if (isPlaying) "▶" else "⏸",
                    fontSize = 13.sp,
                    color = currentFg,
                )
            } else {
                Text(
                    "${item.index + 1}",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(Modifier.width(3.dp))
        Column(Modifier.weight(1f)) {
            // Kapela nad skladbou, rovnako ako v hlavicke — nech sa oko na
            // oboch miestach chyta toho isteho. Nazov skladby je pod nou
            // mensim a tlmenym pismom.
            if (item.artist.isNotEmpty()) {
                Text(
                    item.artist,
                    fontSize = 14.sp,
                    lineHeight = 16.sp,
                    fontWeight = if (isCurrent) FontWeight.Bold else FontWeight.Medium,
                    color = if (isCurrent) currentFg else MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                item.title.ifEmpty { "—" },
                fontSize = if (item.artist.isEmpty()) 14.sp else 11.sp,
                lineHeight = if (item.artist.isEmpty()) 16.sp else 13.sp,
                fontWeight = if (isCurrent && item.artist.isEmpty()) FontWeight.Bold
                else FontWeight.Normal,
                color = if (isCurrent) {
                    if (item.artist.isEmpty()) currentFg else currentFg.copy(alpha = 0.8f)
                } else if (item.artist.isEmpty()) {
                    MaterialTheme.colorScheme.onSurface
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (isCurrent) {
            Spacer(Modifier.width(8.dp))
            Text(
                if (isPlaying) "hrá" else "pauza",
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
                color = currentFg,
            )
        }
        if (item.durationMs > 0) {
            Spacer(Modifier.width(8.dp))
            Text(
                formatTime(item.durationMs),
                fontSize = 12.sp,
                color = if (isCurrent) currentFg.copy(alpha = 0.8f)
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private fun formatTime(ms: Long): String {
    if (ms <= 0) return "0:00"
    val totalSec = ms / 1000
    return "%d:%02d".format(totalSec / 60, totalSec % 60)
}

@Composable
private fun StatusChip(
    discovery: DiscoveryState,
    isPlaying: Boolean,
    isConnecting: Boolean,
    isError: Boolean,
    streamingActive: Boolean,
) {
    // Rovnaké stavové farby ako vo Windows appke (#4caf50 / #ffa000 / #777).
    val (label, color) = when {
        discovery is DiscoveryState.NotFound -> "Server nedostupný" to Color(0xFFE53935)
        discovery is DiscoveryState.Discovering -> "Hľadám server..." to Color(0xFFFFA000)
        isError -> "Chyba prehrávania" to Color(0xFFE53935)
        isConnecting -> "Pripájam..." to Color(0xFFFFA000)
        isPlaying -> "Pripojené" to Color(0xFF4CAF50)
        !streamingActive -> "Server nestrémuje" to Color(0xFF777777)
        else -> "Zastavené" to Color(0xFF777777)
    }

    val isPulsing = discovery is DiscoveryState.Discovering || isConnecting
    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val scale by if (isPulsing) {
        infiniteTransition.animateFloat(
            initialValue = 0.7f,
            targetValue = 1.3f,
            animationSpec = infiniteRepeatable(
                animation = tween(600),
                repeatMode = RepeatMode.Reverse,
            ),
            label = "dot_scale",
        )
    } else {
        remember { mutableStateOf(1f) }
    }

    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(10.dp)
                .scale(scale)
                .background(color, CircleShape)
        )
        Spacer(Modifier.width(8.dp))
        Text(label, fontSize = 14.sp, color = color)
    }
}
