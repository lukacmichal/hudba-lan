# Android self-update z NAS (SMB) — Design Spec

**Dátum:** 2026-07-18
**Stav:** Schválené

## Prehľad

Android klient (`sk.lanmusic`) sa naučí **sám sa aktualizovať** zo Synology NASu
(`nas.local`, shared folder `Android` = `/volume1/Android`) cez SMB.

- Appka zobrazuje **aktuálnu verziu** (⋮ menu).
- Pri štarte ticho pozrie na NAS, či tam nie je novší build.
- Ak je, **sám ho stiahne** na pozadí, overí kontrolný súčet a ponúkne inštaláciu.
- Prístupové údaje na NAS sa zadávajú **v appke**, nie sú zašité v APK.

Motivácia: dnes sa každý nový build kopíruje do telefónu ručne (USB/adb). Cieľom je,
aby stačilo hodiť APK na NAS a telefón si ho našiel sám.

## Rozhodnutia a ich dôvody

| Rozhodnutie | Dôvod |
|---|---|
| SMB (nie HTTP/WebDAV) | Share už existuje a funguje; na NASe netreba inštalovať Web Station ani WebDAV |
| Manifest `latest.json` (nie scan priečinka) | Appka nemusí parsovať názvy súborov; `sha256` odhalí nedokončený upload |
| Údaje v nastaveniach appky (nie v APK) | Pri zmene hesla by zašité údaje zabili self-update a opraviť by sa to dalo len ručným sideloadom |
| Automatické stiahnutie na pozadí | Používateľ potvrdzuje až samotnú inštaláciu (Android to vyžaduje vždy, obísť sa nedá) |
| minSdk 21 → 26 | `REQUEST_INSTALL_PACKAGES` a `canRequestPackageInstalls()` existujú až od API 26 |
| Vlastný release keystore | Android nainštaluje update len pri zhodnom podpise; debug keystore môže AS kedykoľvek pregenerovať |
| Nešifrované `SharedPreferences` | App-private úložisko na nerootnutom telefóne stačí; `androidx.security-crypto` je deprecated a pridal by len krehkosť pre read-only účet na LAN |

## Rozloženie na NASe

```
/volume1/Android/
    latest.json
    lanmusic-1.3.apk
```

`latest.json`:

```json
{
  "versionCode": 4,
  "versionName": "1.3",
  "apk": "lanmusic-1.3.apk",
  "sha256": "a1b2c3…",
  "notes": "Automatické aktualizácie z NASu"
}
```

- `versionCode` — jediné kritérium porovnania (celé číslo, monotónne rastúce).
- `apk` — názov súboru v tom istom priečinku. Staré APK sa nemažú, `latest.json` len ukazuje na aktuálne.
- `sha256` — hex, malé písmená, počítané z celého súboru APK.
- `notes` — voliteľné, zobrazí sa v dialógu.

Na NASe treba účet (napr. `nasuser`) s **read-only** právom na share `Android`
a povoleným SMB prihlásením.

## Data flow

```
štart appky
   │
   ├─▶ sú uložené SMB údaje?  ── nie ─▶ koniec (používateľ ich zadá v nastaveniach)
   │          │ áno
   │          ▼
   │   SMB read latest.json  ── chyba ─▶ ticho koniec, skúsi sa pri ďalšom štarte
   │          │
   │          ▼
   │   versionCode > môj?  ── nie ─▶ koniec
   │          │ áno
   │          ▼
   │   stiahni APK do cache ─▶ over sha256 ── nesedí ─▶ zmaž, koniec
   │          │
   │          ▼
   │   dialóg „Nová verzia 1.3 — Inštalovať?"
   │          │ používateľ potvrdí
   │          ▼
   │   canRequestPackageInstalls()? ── nie ─▶ Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES
   │          │ áno
   │          ▼
   │   FileProvider URI ─▶ ACTION_VIEW (vnd.android.package-archive) ─▶ systémový inštalátor
```

Celý reťazec beží na `Dispatchers.IO` v `viewModelScope`. Nesmie blokovať UI ani
zasahovať do prehrávania streamu.

## Komponenty — `sk.lanmusic.update`

Každý má jednu úlohu a jasné rozhranie. `UpdateChecker` je testovateľný bez siete
(závisí na rozhraní `UpdateSource`, nie na SMB implementácii).

### `UpdateConfig`
Data class + načítanie/uloženie do `SharedPreferences` (`lanmusic_update`).

```kotlin
data class UpdateConfig(
    val host: String = "nas.local",
    val share: String = "Android",
    val username: String = "",
    val password: String = "",
) {
    val isComplete: Boolean get() = host.isNotBlank() && share.isNotBlank() && username.isNotBlank()
}
```

Predvolený host a share sú predvyplnené, používateľ dopĺňa len meno a heslo.

### `UpdateManifest`
Data class + parsovanie `latest.json` cez `org.json.JSONObject` (v Androide, bez závislosti).
Chýbajúce alebo nečíselné `versionCode` → `null` (manifest sa ignoruje).

### `UpdateSource` (rozhranie) + `SmbUpdateSource`
```kotlin
interface UpdateSource {
    suspend fun fetchManifest(cfg: UpdateConfig): UpdateManifest
    suspend fun downloadApk(cfg: UpdateConfig, name: String, target: File, onProgress: (Float) -> Unit)
}
```
`SmbUpdateSource` implementuje cez `smbj` (SMB 2/3 — Synology má SMB1 vypnuté).
Fallback pri integračných problémoch: `jcifs-ng`.

### `UpdateChecker`
Orchestrácia: porovná `manifest.versionCode` s nainštalovanou verziou
(`packageManager.getPackageInfo(packageName, 0).longVersionCode` — nepotrebuje `BuildConfig`),
stiahne, overí sha256, vystaví `StateFlow<UpdateState>`.

Cieľ sťahovania: `context.cacheDir/updates/<apk>`. Priečinok sa pred stiahnutím vyčistí,
aby sa nehromadili staré buildy.

### `ApkInstaller`
`FileProvider` URI + `ACTION_VIEW` s `FLAG_GRANT_READ_URI_PERMISSION`.
Ak `canRequestPackageInstalls()` je `false`, najprv pošle používateľa do
`Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES`.

### `UpdateState`
```kotlin
sealed interface UpdateState {
    object Idle : UpdateState
    object Checking : UpdateState
    object UpToDate : UpdateState
    object NotConfigured : UpdateState
    data class Downloading(val progress: Float) : UpdateState
    data class ReadyToInstall(val manifest: UpdateManifest, val file: File) : UpdateState
    data class Failed(val reason: String) : UpdateState
}
```

## UI

V ⋮ overflow menu (`PlayerScreen.kt`) pribudnú dve položky:

- **Verzia 1.3** — needitovateľný riadok s aktuálnou verziou.
- **Skontrolovať aktualizácie** — vynúti kontrolu, zobrazí výsledok (aj `UpToDate`).
- **Nastavenia aktualizácií** — dialóg:

```
NAS adresa   [nas.local]
Share        [Android]
Meno         [            ]
Heslo        [            ]   (PasswordVisualTransformation)
                    [ Otestovať spojenie ]
```

*Otestovať spojenie* sa naozaj pripojí a načíta `latest.json`, aby chyba rozlíšila
zlé heslo / chýbajúce práva / nedostupný NAS. Výsledok sa zobrazí priamo v dialógu.

Dialóg novej verzie: názov verzie, `notes`, tlačidlá **Inštalovať** / **Neskôr**.
Automatický štartovací check zobrazí dialóg len v stave `ReadyToInstall` — priebeh
kontroly a sťahovania je ticho na pozadí. Manuálna kontrola z menu zobrazuje aj
`Checking` / `Downloading` / `Failed`.

Motív a štýl podľa existujúcej `Theme.kt` (MetalTheme).

## Zmeny mimo `update` balíka

### `AndroidManifest.xml`
```xml
<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />

<provider
    android:name="androidx.core.content.FileProvider"
    android:authorities="${applicationId}.fileprovider"
    android:exported="false"
    android:grantUriPermissions="true">
    <meta-data android:name="android.support.FILE_PROVIDER_PATHS"
               android:resource="@xml/file_paths" />
</provider>
```
`res/xml/file_paths.xml` vystaví `cache/updates`.

### `app/build.gradle.kts`
- `minSdk 21` → `26`
- `versionCode 3` → `4`, `versionName "1.2"` → `"1.3"`
- `signingConfigs.release` čítaný z `keystore.properties`
- závislosť `smbj` + `slf4j-nop` (smbj vyžaduje slf4j binding, inak spamuje log)

### Podpisovanie
Nový keystore `android/keystore/lanmusic.jks`, údaje v `android/keystore.properties`
(neverzuje sa — projekt zatiaľ nie je git repo, ale súbor je tak označený pre budúcnosť).

**Dôsledok pre používateľa:** prvý release-podpísaný build sa nedá nainštalovať
cez existujúcu debug-podpísanú appku. Starú appku treba raz odinštalovať a novú
nainštalovať načisto. Všetky ďalšie aktualizácie už pôjdu automaticky.

### `publish-apk.ps1`
Skript v `android/`, ktorý po builde:
1. skopíruje `app-release.apk` na `\\nas.local\Android\lanmusic-<verzia>.apk`,
2. spočíta SHA-256,
3. vygeneruje a prepíše `latest.json`.

Verziu si prečíta z `build.gradle.kts`, aby sa nemohla rozísť s APK.
Zmysel: `latest.json` sa nikdy nepíše ručne — to je hlavný zdroj chýb pri tomto vzore.

## Ošetrenie chýb

| Situácia | Správanie |
|---|---|
| NAS nedostupný (iná sieť, mobilné dáta) | Ticho, log; skúsi sa pri ďalšom štarte |
| Chýbajúce/nekompletné údaje | `NotConfigured`, štartovací check sa nespustí |
| Zlé heslo / chýbajúce práva | Pri manuálnej kontrole konkrétna hláška; pri automatickej ticho |
| `latest.json` chýba alebo je nevalidný | Ignoruje sa |
| `versionCode` ≤ nainštalovaná | `UpToDate` |
| Prerušené sťahovanie | Súbor sa zmaže, žiadny dialóg |
| Nesúhlasí `sha256` | Súbor sa zmaže, `Failed` |
| Používateľ nepovolí neznáme zdroje | Presmerovanie do nastavení, stav ostáva `ReadyToInstall` |

Zásada: **automatická** kontrola nikdy neruší používateľa chybou. Chyby sú hlasné
len pri manuálnej kontrole a v teste spojenia, kde ich používateľ očakáva.

## Testovanie

**JVM unit testy** (`app/src/test/`) — logika bez Androidu a bez siete:
- parsovanie `latest.json` (validný, chýbajúce polia, nevalidný JSON)
- porovnanie verzií (novšia / rovnaká / staršia)
- `UpdateChecker` s fake `UpdateSource` — prechody stavov vrátane zlyhania sha256

**Manuálne na zariadení** (nedá sa zmysluplne automatizovať):
- test spojenia so správnymi aj zlými údajmi
- reálny update z verzie 4 na 5 vrátane inštalácie
- správanie mimo dosahu NASu

Projekt zatiaľ nemá Android test infraštruktúru — pridá sa `testImplementation`
pre JUnit. Python testy PC backendu ostávajú nedotknuté (self-update sa ich netýka).

## Poradie implementácie

SMB knižnica je jediný kus s reálnym integračným rizikom, preto ide **prvá** —
overiť, že `smbj` zbuildí na Androide a spojí sa s NASom, skôr než sa postaví
zvyšok. Až potom keystore, logika, UI a publish skript.

## Mimo rozsahu

- Delta/inkrementálne aktualizácie (APK je malé, nemá zmysel)
- Downgrade na staršiu verziu
- Viacero release kanálov (stable/beta)
- Aktualizácia PC appky rovnakým mechanizmom
