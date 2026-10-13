package sk.lanmusic

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.material3.Surface
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import sk.lanmusic.service.StreamService
import sk.lanmusic.ui.MetalTheme
import sk.lanmusic.ui.PlayerScreen
import sk.lanmusic.ui.PlayerViewModel

class MainActivity : ComponentActivity() {

    private val viewModel: PlayerViewModel by viewModels()
    private var isBound = false

    /** Widget chce appku rovno na touchpade. Po otvoreni sa vynuluje. */
    private var touchpadZiadost by mutableStateOf(false)

    private fun precitajZiadost(intent: Intent?) {
        if (intent?.getBooleanExtra(EXTRA_TOUCHPAD, false) == true) {
            touchpadZiadost = true
            // Po otoceni obrazovky sa Activity vytvori znova s tym istym
            // intentom — zavrety touchpad sa nesmie otvorit sam od seba.
            intent.removeExtra(EXTRA_TOUCHPAD)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        precitajZiadost(intent)
    }

    /**
     * Velkost pisma z Nastaveni. Appka bezi na Compose a nema
     * `AppCompatDelegate`, takze sa `fontScale` prepisuje priamo v konfiguracii
     * kontextu — skor, nez sa nakresli cokolvek. Cierny rezim si berie
     * `MetalTheme` z [Vzhlad] sam.
     */
    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(Vzhlad.obal(newBase))
    }

    /**
     * Poistka pre pocitadlo dat: polling metadat aj kontrola aktualizacie su
     * bez Androidu a bajty len nazbieraju ([Prenos.nazbieraj]). Tu je prvy
     * bod, kde je po nich Context.
     */
    override fun onResume() {
        super.onResume()
        Prenos.odovzdaj(this)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) precitajZiadost(intent)
        setContent {
            MetalTheme {
                Surface {
                    val uiState by viewModel.uiState.collectAsState()
                    PlayerScreen(
                        uiState = uiState,
                        onPrev = viewModel::onPrev,
                        onPlayPause = viewModel::onPlayPause,
                        onNext = viewModel::onNext,
                        onStop = viewModel::onStopRemote,
                        onSeek = viewModel::onSeek,
                        onVolume = viewModel::onVolume,
                        onToggleMute = viewModel::onToggleMute,
                        onPlayIndex = viewModel::onPlayIndex,
                        onShutdown = viewModel::onShutdown,
                        onSleep = viewModel::onSleep,
                        onSleep2 = viewModel::onSleep2,
                        onToggleListening = viewModel::onToggleListening,
                        onReconnectClicked = viewModel::onReconnectClicked,
                        onExitClicked = {
                            viewModel.onExitClicked()
                            finishAndRemoveTask()
                        },
                        onCheckUpdates = { viewModel.checkForUpdates() },
                        onConfirmUpdate = viewModel::onConfirmUpdate,
                        onInstallUpdate = viewModel::onInstallUpdate,
                        onDismissUpdate = viewModel::onDismissUpdate,
                        onSaveUpdateSettings = viewModel::onUpdateSettingsSaved,
                        onSaveManualServer = viewModel::onManualServerSaved,
                        onTestConnection = viewModel::testConnection,
                        touchpadZiadost = touchpadZiadost,
                        onTouchpadZiadostVybavena = { touchpadZiadost = false },
                    )
                }
            }
        }
    }

    /**
     * Sluzba sa tu uz LEN ZVIAZE, nespusta sa do popredia.
     *
     * Do 27. 8. 2026 tu bolo `startForegroundService`, takze len otvorenim
     * appky vznikla trvala notifikacia a s nou ovladanie na zamknutej
     * obrazovke — aj ked sa do telefonu nic nestreamovalo. Do popredia sa
     * sluzba dostane az v `StreamService.play()`, teda az ked si clovek
     * zapne pocuvanie.
     *
     * `BIND_AUTO_CREATE` sluzbu vytvori (a s nou LibVLC aj vyhladavanie
     * v sieti), takze appka funguje ako dialkove ovladanie PC aj bez
     * prehravania — len o sebe nedava vediet na zamknutej obrazovke.
     */
    override fun onStart() {
        super.onStart()
        val intent = Intent(this, StreamService::class.java)
        isBound = bindService(intent, viewModel.serviceConnection, BIND_AUTO_CREATE)
    }

    companion object {
        const val EXTRA_TOUCHPAD = "sk.lanmusic.TOUCHPAD"
    }

    override fun onStop() {
        super.onStop()
        if (isBound) {
            unbindService(viewModel.serviceConnection)
            isBound = false
        }
    }
}
