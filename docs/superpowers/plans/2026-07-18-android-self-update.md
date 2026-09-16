# Android self-update z NAS (SMB) — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Android klient `sk.lanmusic` si pri štarte sám nájde novší build na Synology NASe cez SMB, stiahne ho, overí a ponúkne inštaláciu.

**Architecture:** Nový balík `sk.lanmusic.update` s rozhraním `UpdateSource` (SMB implementácia oddelená od logiky), `UpdateChecker` ako čistá Kotlin trieda testovateľná bez siete a bez Androidu, `ApkInstaller` cez FileProvider. Konfigurácia (NAS účet) v `SharedPreferences`, zadáva sa v appke. Kontrola beží na `Dispatchers.IO`, nikdy neblokuje UI ani prehrávanie.

**Tech Stack:** Kotlin, Compose Material3, smbj (SMB 2/3), org.json, JUnit4.

**Spec:** `docs/superpowers/specs/2026-07-18-android-self-update-design.md`

---

## Poznámky pre implementátora — prečítaj pred začatím

**1. `C:\music` nie je git repo.** Kroky „Commit" v tomto pláne predpokladajú, že sa spraví Task 0. Ak sa používateľ rozhodne git nezakladať, kroky s commitom preskoč — všetko ostatné platí bez zmeny.

**2. Kanonický adresár je `C:\music\android`.** Existuje starý duplikát `C:\music\music\android` z 31.3. — **needituj ho**. Overiť si to vieš tým, že `app/src/main/java/sk/lanmusic/ui/Theme.kt` existuje len v kanonickom.

**3. Build:** `android\gradlew.bat -p android assembleDebug`. Android SDK je `C:\Users\<pouzivatel>\AppData\Local\Android\Sdk`. AGP 8.3.2 vs compileSdk 35 hádže warning — je to očakávané, build prejde.

**4. Jazyk:** komentáre v kóde po anglicky, UI reťazce po slovensky. Tak je to v existujúcom kóde.

**5. Poradie nie je náhodné.** Chunk 1 obsahuje jediný kus s reálnym integračným rizikom (SMB knižnica na Androide). Ak zlyhá, zvyšok plánu sa nemá zmysel stavať — preto ide prvý.

---

## Chunk 1: Základy a SMB spike

Cieľ chunku: overené, že sa vieme z Androidu pripojiť na NAS a prečítať súbor. Bez toho nemá zmysel pokračovať.

### Task 0: Git repozitár (voliteľné, odporúčané)

Dôvod: pribudne keystore a heslá, ktoré sa nesmú verzovať, a self-updating appka bez histórie je nepríjemná na debugovanie.

**Files:**
- Create: `C:\music\.gitignore`

- [ ] **Step 1: Inicializuj repo**

```bash
cd /c/music && git init
```

- [ ] **Step 2: Vytvor `.gitignore`**

```gitignore
# Android
android/.gradle/
android/build/
android/app/build/
android/local.properties
android/.idea/
android/keystore.properties
android/keystore/

# Python
__pycache__/
*.pyc
.venv/
venv/

# Windows
Thumbs.db
desktop.ini
```

- [ ] **Step 3: Prvý commit**

```bash
cd /c/music && git add -A && git commit -m "chore: initial commit before self-update feature"
```

Očakávaj: commit prejde. Ak `git` hlási identitu, nastav `user.email` / `user.name`.

---

### Task 1: SMB spike — dokáž, že sa vieme pripojiť

**Toto je risk task. Nepokračuj na Task 2, kým tento neprejde.**

**Files:**
- Modify: `android/gradle/libs.versions.toml`
- Modify: `android/app/build.gradle.kts`
- Create: `android/app/src/androidTest/java/sk/lanmusic/SmbSpikeTest.kt` (dočasný, na konci chunku sa zmaže)

- [ ] **Step 1: Pridaj smbj do version catalogu**

V `android/gradle/libs.versions.toml`, do `[versions]`:

```toml
smbj = "0.14.0"
slf4j = "2.0.13"
```

Do `[libraries]`:

```toml
smbj = { group = "com.hierynomus", name = "smbj", version.ref = "smbj" }
slf4j-nop = { group = "org.slf4j", name = "slf4j-nop", version.ref = "slf4j" }
```

- [ ] **Step 2: Zdvihni minSdk a pridaj závislosti**

V `android/app/build.gradle.kts` zmeň `minSdk = 21` na `minSdk = 26`.

Dôvod: `REQUEST_INSTALL_PACKAGES` / `canRequestPackageInstalls()` sú API 26+, a smbj používa `java.time`, ktoré je na Androide tiež až od API 26. Jedna zmena rieši oboje.

Do `dependencies` pridaj:

```kotlin
implementation(libs.smbj)
implementation(libs.slf4j.nop)
```

`slf4j-nop` nie je kozmetika — bez slf4j bindingu smbj pri každom volaní zaspamuje logcat varovaniami.

- [ ] **Step 3: Skús zbuildiť**

```bash
cd /c/music && android/gradlew.bat -p android assembleDebug
```

Očakávaj: BUILD SUCCESSFUL.

**Ak build zlyhá** — najpravdepodobnejšie príčiny, v poradí:

| Chyba | Riešenie |
|---|---|
| `Duplicate class org.bouncycastle...` | Pridaj do `dependencies`: `implementation(libs.smbj) { exclude(group = "org.bouncycastle") }` a doplň jednu konkrétnu verziu `implementation("org.bouncycastle:bcprov-jdk18on:1.78")` |
| `Program type already present` / dex limit | Zapni `multiDexEnabled = true` v `defaultConfig` |
| Chýbajúca `javax.naming.*` trieda | smbj na Androide nefunguje → prepni na fallback (Step 6) |

- [ ] **Step 4: Napíš spike test**

Toto je **inštrumentovaný** test — musí bežať na reálnom zariadení v sieti s NASom, nie na JVM.

Do `android/app/build.gradle.kts` → `dependencies`:

```kotlin
androidTestImplementation("androidx.test.ext:junit:1.1.5")
androidTestImplementation("androidx.test:runner:1.5.2")
```

A do `defaultConfig`:

```kotlin
testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
```

`android/app/src/androidTest/java/sk/lanmusic/SmbSpikeTest.kt`:

```kotlin
package sk.lanmusic

import com.hierynomus.msdtyp.AccessMask
import com.hierynomus.mssmb2.SMB2CreateDisposition
import com.hierynomus.mssmb2.SMB2ShareAccess
import com.hierynomus.smbj.SMBClient
import com.hierynomus.smbj.auth.AuthenticationContext
import com.hierynomus.smbj.share.DiskShare
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.EnumSet

/** Temporary spike: proves smbj can reach the NAS from a real device. */
class SmbSpikeTest {

    // TODO fill in before running — do NOT commit real credentials
    private val host = "nas.local"
    private val share = "Android"
    private val user = "nasuser"
    private val pass = "REPLACE_ME"

    @Test
    fun canReadLatestJson() {
        val client = SMBClient()
        client.connect(host).use { conn ->
            val session = conn.authenticate(
                AuthenticationContext(user, pass.toCharArray(), null)
            )
            (session.connectShare(share) as DiskShare).use { disk ->
                val f = disk.openFile(
                    "latest.json",
                    EnumSet.of(AccessMask.GENERIC_READ),
                    null,
                    SMB2ShareAccess.ALL,
                    SMB2CreateDisposition.FILE_OPEN,
                    null,
                )
                val text = f.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
                println("SPIKE latest.json = $text")
                assertTrue(text.isNotBlank())
            }
        }
    }
}
```

- [ ] **Step 5: Priprav NAS a spusti spike**

Na NASe musí existovať `\\nas.local\Android\latest.json`. Zatiaľ stačí dočasný obsah:

```json
{"versionCode": 1, "versionName": "0.0", "apk": "none.apk", "sha256": ""}
```

Telefón musí byť na USB a na tej istej WiFi.

```bash
cd /c/music && android/gradlew.bat -p android connectedDebugAndroidTest
```

Očakávaj: test PASS, v logu `SPIKE latest.json = {...}`.

Ak zlyhá na `SMBApiException: STATUS_LOGON_FAILURE` → zlé meno/heslo alebo účet nemá SMB prístup.
Ak zlyhá na `STATUS_ACCESS_DENIED` → účet nemá práva na share.
Ak zlyhá na timeout → firewall na NASe alebo iná VLAN.

- [ ] **Step 6: Ak smbj nefunguje — fallback na jcifs-ng**

Len ak Step 3 alebo Step 5 nešlo rozumne opraviť. Vymeň závislosť:

```toml
jcifs-ng = { group = "eu.agno3.jcifs", name = "jcifs-ng", version = "2.1.10" }
```

a spike prepíš na:

```kotlin
val props = java.util.Properties().apply {
    setProperty("jcifs.smb.client.minVersion", "SMB202")
    setProperty("jcifs.smb.client.maxVersion", "SMB311")
}
val ctx = jcifs.context.BaseContext(jcifs.config.PropertyConfiguration(props))
    .withCredentials(jcifs.smb.NtlmPasswordAuthenticator(null, user, pass))
val text = jcifs.smb.SmbFile("smb://$host/$share/latest.json", ctx)
    .inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
```

Zvyšok plánu ostáva platný — mení sa len vnútro `SmbUpdateSource` (Task 5), rozhranie nie.

- [ ] **Step 7: Zmaž spike a commitni**

Spike splnil účel a obsahuje heslo — musí zmiznúť.

```bash
rm C:/music/android/app/src/androidTest/java/sk/lanmusic/SmbSpikeTest.kt
cd /c/music && git add -A && git commit -m "feat(android): add smbj dependency, raise minSdk to 26"
```

`androidTestImplementation` závislosti a `testInstrumentationRunner` **nechaj** — zídu sa.

---

## Chunk 2: Logika aktualizácií (TDD, bez Androidu a bez siete)

Celý tento chunk je čistá Kotlin logika testovateľná na JVM. Žiadny emulátor, žiadny NAS.

### Task 2: Test infraštruktúra pre JVM testy

**Files:**
- Modify: `android/app/build.gradle.kts`

- [ ] **Step 1: Pridaj testovacie závislosti**

```kotlin
testImplementation("junit:junit:4.13.2")
testImplementation("org.json:json:20240303")
```

**`org.json:json` je kritické a nie je zbytočné.** Android má `org.json` zabudované, ale v JVM unit testoch je to prázdny stub, ktorý pri každom volaní hodí `RuntimeException: Method ... not mocked`. Táto závislosť dodá skutočnú implementáciu na test classpath. Bez nej padnú všetky testy parsovania manifestu spôsobom, ktorý vyzerá ako chyba v tvojom kóde, hoci nie je.

- [ ] **Step 2: Over, že sa testy vôbec spúšťajú**

```bash
cd /c/music && android/gradlew.bat -p android testDebugUnitTest
```

Očakávaj: BUILD SUCCESSFUL, 0 testov.

- [ ] **Step 3: Commit**

```bash
cd /c/music && git add -A && git commit -m "chore(android): add JVM unit test dependencies"
```

---

### Task 3: `UpdateManifest` — parsovanie `latest.json`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/update/UpdateManifest.kt`
- Test: `android/app/src/test/java/sk/lanmusic/update/UpdateManifestTest.kt`

- [ ] **Step 1: Napíš padajúce testy**

```kotlin
package sk.lanmusic.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UpdateManifestTest {

    @Test
    fun `parses a valid manifest`() {
        val json = """
            {"versionCode": 4, "versionName": "1.3", "apk": "lanmusic-1.3.apk",
             "sha256": "ABC123", "notes": "nieco"}
        """.trimIndent()

        val m = UpdateManifest.parse(json)!!

        assertEquals(4L, m.versionCode)
        assertEquals("1.3", m.versionName)
        assertEquals("lanmusic-1.3.apk", m.apk)
        assertEquals("abc123", m.sha256)   // normalised to lowercase
        assertEquals("nieco", m.notes)
    }

    @Test
    fun `notes and sha256 are optional`() {
        val m = UpdateManifest.parse("""{"versionCode":4,"versionName":"1.3","apk":"a.apk"}""")!!
        assertEquals("", m.sha256)
        assertEquals("", m.notes)
    }

    @Test
    fun `returns null on malformed json`() {
        assertNull(UpdateManifest.parse("this is not json"))
    }

    @Test
    fun `returns null when versionCode is missing`() {
        assertNull(UpdateManifest.parse("""{"versionName":"1.3","apk":"a.apk"}"""))
    }

    @Test
    fun `returns null when versionCode is not a number`() {
        assertNull(UpdateManifest.parse("""{"versionCode":"x","versionName":"1.3","apk":"a.apk"}"""))
    }

    @Test
    fun `returns null when apk name is blank`() {
        assertNull(UpdateManifest.parse("""{"versionCode":4,"versionName":"1.3","apk":""}"""))
    }

    @Test
    fun `rejects apk names containing a path separator`() {
        // A manifest must not be able to point outside the share directory.
        assertNull(UpdateManifest.parse("""{"versionCode":4,"versionName":"1.3","apk":"../x.apk"}"""))
        assertNull(UpdateManifest.parse("""{"versionCode":4,"versionName":"1.3","apk":"sub/x.apk"}"""))
    }
}
```

- [ ] **Step 2: Spusti, over že padajú**

```bash
cd /c/music && android/gradlew.bat -p android testDebugUnitTest --tests "*UpdateManifestTest*"
```

Očakávaj: FAIL — `Unresolved reference: UpdateManifest`.

- [ ] **Step 3: Implementuj**

```kotlin
package sk.lanmusic.update

import org.json.JSONObject

/** Contents of latest.json on the NAS share. */
data class UpdateManifest(
    val versionCode: Long,
    val versionName: String,
    val apk: String,
    val sha256: String,
    val notes: String,
) {
    companion object {
        /** Returns null for anything we cannot trust; callers treat null as "no update". */
        fun parse(text: String): UpdateManifest? = try {
            val o = JSONObject(text)
            val code = o.optLong("versionCode", -1L)
            val apk = o.optString("apk", "")
            when {
                code <= 0L -> null
                apk.isBlank() -> null
                // Keep the manifest confined to the share root.
                apk.contains('/') || apk.contains('\\') -> null
                else -> UpdateManifest(
                    versionCode = code,
                    versionName = o.optString("versionName", ""),
                    apk = apk,
                    sha256 = o.optString("sha256", "").lowercase(),
                    notes = o.optString("notes", ""),
                )
            }
        } catch (e: Exception) {
            null
        }
    }
}
```

Pozn.: `optLong("versionCode", -1L)` vráti default aj pre `"x"`, čím prejde test na nečíselnú hodnotu.

- [ ] **Step 4: Spusti testy**

```bash
cd /c/music && android/gradlew.bat -p android testDebugUnitTest --tests "*UpdateManifestTest*"
```

Očakávaj: PASS, 7 testov.

- [ ] **Step 5: Commit**

```bash
cd /c/music && git add -A && git commit -m "feat(android): parse update manifest"
```

---

### Task 4: `UpdateConfig`, `UpdateSource`, `UpdateState`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/update/UpdateConfig.kt`
- Create: `android/app/src/main/java/sk/lanmusic/update/UpdateSource.kt`
- Create: `android/app/src/main/java/sk/lanmusic/update/UpdateState.kt`
- Test: `android/app/src/test/java/sk/lanmusic/update/UpdateConfigTest.kt`

- [ ] **Step 1: Napíš padajúci test na `isComplete`**

```kotlin
package sk.lanmusic.update

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateConfigTest {

    @Test
    fun `defaults are prefilled but incomplete without a username`() {
        val c = UpdateConfig()
        assertEquals("nas.local", c.host)
        assertEquals("Android", c.share)
        assertFalse(c.isComplete)
    }

    @Test
    fun `complete once a username is present`() {
        assertTrue(UpdateConfig(username = "nasuser").isComplete)
    }

    @Test
    fun `blank host makes it incomplete`() {
        assertFalse(UpdateConfig(host = "  ", username = "nasuser").isComplete)
    }
}
```

Nezabudni doimportovať `org.junit.Assert.assertEquals`.

- [ ] **Step 2: Over, že padá**

```bash
cd /c/music && android/gradlew.bat -p android testDebugUnitTest --tests "*UpdateConfigTest*"
```

Očakávaj: FAIL — `Unresolved reference: UpdateConfig`.

- [ ] **Step 3: Implementuj `UpdateConfig`**

Prázdne heslo je legitímne (guest účet), preto do `isComplete` nevstupuje.

```kotlin
package sk.lanmusic.update

/** NAS connection settings, entered by the user in the app. */
data class UpdateConfig(
    val host: String = "nas.local",
    val share: String = "Android",
    val username: String = "",
    val password: String = "",
) {
    val isComplete: Boolean
        get() = host.isNotBlank() && share.isNotBlank() && username.isNotBlank()
}
```

- [ ] **Step 4: Implementuj `UpdateSource`**

```kotlin
package sk.lanmusic.update

import java.io.File

/**
 * Where updates come from. Kept as an interface so UpdateChecker can be
 * tested without a network, and so the SMB library can be swapped out.
 */
interface UpdateSource {
    /** Reads and parses latest.json. Throws on any I/O or auth failure. */
    suspend fun fetchManifest(cfg: UpdateConfig): UpdateManifest?

    /** Downloads [name] from the share root into [target]. */
    suspend fun downloadApk(
        cfg: UpdateConfig,
        name: String,
        target: File,
        onProgress: (Float) -> Unit,
    )
}
```

- [ ] **Step 5: Implementuj `UpdateState`**

```kotlin
package sk.lanmusic.update

import java.io.File

sealed interface UpdateState {
    data object Idle : UpdateState
    data object NotConfigured : UpdateState
    data object Checking : UpdateState
    data object UpToDate : UpdateState
    data class Downloading(val progress: Float) : UpdateState
    data class ReadyToInstall(val manifest: UpdateManifest, val file: File) : UpdateState
    data class Failed(val reason: String) : UpdateState
}
```

- [ ] **Step 6: Spusti testy**

```bash
cd /c/music && android/gradlew.bat -p android testDebugUnitTest --tests "*UpdateConfigTest*"
```

Očakávaj: PASS, 3 testy.

- [ ] **Step 7: Commit**

```bash
cd /c/music && git add -A && git commit -m "feat(android): update config, source interface and state"
```

---

### Task 5: `UpdateChecker` — jadro logiky

Toto je najdôležitejší test v pláne. Pokrýva presne tie prechody, ktoré sa na zariadení testujú ťažko.

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/update/UpdateChecker.kt`
- Test: `android/app/src/test/java/sk/lanmusic/update/UpdateCheckerTest.kt`

- [ ] **Step 1: Pridaj coroutines test závislosť**

```kotlin
testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
```

- [ ] **Step 2: Napíš padajúce testy**

```kotlin
package sk.lanmusic.update

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest

class UpdateCheckerTest {

    @get:Rule val tmp = TemporaryFolder()

    private val cfg = UpdateConfig(username = "nasuser")

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it) }

    /** Fake source: serves a manifest and fixed APK bytes, no network. */
    private class FakeSource(
        val manifest: UpdateManifest?,
        val apkBytes: ByteArray = ByteArray(0),
        val failManifest: Boolean = false,
        val failDownload: Boolean = false,
    ) : UpdateSource {
        override suspend fun fetchManifest(cfg: UpdateConfig): UpdateManifest? {
            if (failManifest) throw java.io.IOException("nas down")
            return manifest
        }
        override suspend fun downloadApk(
            cfg: UpdateConfig, name: String, target: File, onProgress: (Float) -> Unit,
        ) {
            if (failDownload) throw java.io.IOException("interrupted")
            target.parentFile?.mkdirs()
            target.writeBytes(apkBytes)
            onProgress(1f)
        }
    }

    private fun manifest(code: Long, sha: String = "") =
        UpdateManifest(code, "9.9", "lanmusic-9.9.apk", sha, "")

    private fun checker(source: UpdateSource, installed: Long = 4L) =
        UpdateChecker(
            source = source,
            cacheDir = tmp.root,
            currentVersionCode = { installed },
        )

    @Test
    fun `newer version downloads and becomes ready to install`() = runTest {
        val apk = "fake apk".toByteArray()
        val c = checker(FakeSource(manifest(5, sha256(apk)), apk))

        c.check(cfg)

        val state = c.state.value
        assertTrue("was $state", state is UpdateState.ReadyToInstall)
        val ready = state as UpdateState.ReadyToInstall
        assertEquals(5L, ready.manifest.versionCode)
        assertTrue(ready.file.exists())
        assertEquals("fake apk", ready.file.readText())
    }

    @Test
    fun `same version code is up to date`() = runTest {
        val c = checker(FakeSource(manifest(4)))
        c.check(cfg)
        assertEquals(UpdateState.UpToDate, c.state.value)
    }

    @Test
    fun `older version code is up to date`() = runTest {
        val c = checker(FakeSource(manifest(3)))
        c.check(cfg)
        assertEquals(UpdateState.UpToDate, c.state.value)
    }

    @Test
    fun `incomplete config short-circuits without touching the source`() = runTest {
        val c = checker(FakeSource(manifest(9)))
        c.check(UpdateConfig())          // no username
        assertEquals(UpdateState.NotConfigured, c.state.value)
    }

    @Test
    fun `unreachable nas fails without crashing`() = runTest {
        val c = checker(FakeSource(null, failManifest = true))
        c.check(cfg)
        assertTrue(c.state.value is UpdateState.Failed)
    }

    @Test
    fun `unparseable manifest is treated as up to date`() = runTest {
        val c = checker(FakeSource(null))
        c.check(cfg)
        assertEquals(UpdateState.UpToDate, c.state.value)
    }

    @Test
    fun `checksum mismatch deletes the file and fails`() = runTest {
        val apk = "fake apk".toByteArray()
        val c = checker(FakeSource(manifest(5, sha256("different".toByteArray())), apk))

        c.check(cfg)

        assertTrue(c.state.value is UpdateState.Failed)
        val leftovers = File(tmp.root, "updates").listFiles().orEmpty()
        assertEquals("downloaded file must not survive", 0, leftovers.size)
    }

    @Test
    fun `empty sha256 skips verification`() = runTest {
        val apk = "fake apk".toByteArray()
        val c = checker(FakeSource(manifest(5, ""), apk))
        c.check(cfg)
        assertTrue(c.state.value is UpdateState.ReadyToInstall)
    }

    @Test
    fun `failed download leaves no file behind`() = runTest {
        val c = checker(FakeSource(manifest(5, "aa"), failDownload = true))
        c.check(cfg)
        assertTrue(c.state.value is UpdateState.Failed)
        val leftovers = File(tmp.root, "updates").listFiles().orEmpty()
        assertEquals(0, leftovers.size)
    }

    @Test
    fun `stale downloads are cleared before a new one`() = runTest {
        val updates = File(tmp.root, "updates").apply { mkdirs() }
        val stale = File(updates, "old-1.0.apk").apply { writeText("old") }

        val apk = "new apk".toByteArray()
        checker(FakeSource(manifest(5, sha256(apk)), apk)).check(cfg)

        assertTrue("stale build should be gone", !stale.exists())
    }
}
```

- [ ] **Step 3: Over, že padajú**

```bash
cd /c/music && android/gradlew.bat -p android testDebugUnitTest --tests "*UpdateCheckerTest*"
```

Očakávaj: FAIL — `Unresolved reference: UpdateChecker`.

- [ ] **Step 4: Implementuj**

```kotlin
package sk.lanmusic.update

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import java.security.MessageDigest

/**
 * Decides whether an update is needed and prepares it for install.
 *
 * Deliberately free of Android APIs: the installed version arrives as a
 * lambda and the download target as a plain File, so the whole decision
 * path is unit-testable without a device or a network.
 */
class UpdateChecker(
    private val source: UpdateSource,
    private val cacheDir: File,
    private val currentVersionCode: () -> Long,
) {
    private val _state = MutableStateFlow<UpdateState>(UpdateState.Idle)
    val state: StateFlow<UpdateState> = _state.asStateFlow()

    private val updatesDir: File get() = File(cacheDir, "updates")

    suspend fun check(cfg: UpdateConfig) {
        if (!cfg.isComplete) {
            _state.value = UpdateState.NotConfigured
            return
        }
        _state.value = UpdateState.Checking

        val manifest = try {
            source.fetchManifest(cfg)
        } catch (e: Exception) {
            _state.value = UpdateState.Failed(e.friendlyMessage())
            return
        }

        // A missing or unreadable manifest is not an error the user can act
        // on — treat it the same as "nothing new".
        if (manifest == null || manifest.versionCode <= currentVersionCode()) {
            _state.value = UpdateState.UpToDate
            return
        }

        // Never accumulate old builds in the cache.
        updatesDir.deleteRecursively()
        updatesDir.mkdirs()
        val target = File(updatesDir, manifest.apk)

        _state.value = UpdateState.Downloading(0f)
        try {
            source.downloadApk(cfg, manifest.apk, target) { p ->
                _state.value = UpdateState.Downloading(p.coerceIn(0f, 1f))
            }
        } catch (e: Exception) {
            updatesDir.deleteRecursively()
            _state.value = UpdateState.Failed(e.friendlyMessage())
            return
        }

        if (manifest.sha256.isNotBlank()) {
            val actual = sha256Of(target)
            if (!actual.equals(manifest.sha256, ignoreCase = true)) {
                updatesDir.deleteRecursively()
                _state.value = UpdateState.Failed(
                    "Kontrolný súčet nesedí — súbor je poškodený alebo neúplný."
                )
                return
            }
        }

        _state.value = UpdateState.ReadyToInstall(manifest, target)
    }

    fun reset() { _state.value = UpdateState.Idle }

    private fun sha256Of(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(8192)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                digest.update(buf, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}

private fun Exception.friendlyMessage(): String =
    message?.takeIf { it.isNotBlank() } ?: (this::class.simpleName ?: "Neznáma chyba")
```

- [ ] **Step 5: Spusti testy**

```bash
cd /c/music && android/gradlew.bat -p android testDebugUnitTest --tests "*UpdateCheckerTest*"
```

Očakávaj: PASS, 10 testov.

- [ ] **Step 6: Commit**

```bash
cd /c/music && git add -A && git commit -m "feat(android): update checker with checksum verification"
```

---

## Chunk 3: Android integrácia

Od tejto chvíle sa už testuje na zariadení. JVM testy z Chunku 2 musia stále prechádzať.

### Task 6: `SmbUpdateSource`

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/update/SmbUpdateSource.kt`

- [ ] **Step 1: Implementuj**

Použi to, čo sa osvedčilo v spike (Task 1). Ak si musel prejsť na jcifs-ng, prepíš len vnútro metód — signatúry ostávajú.

```kotlin
package sk.lanmusic.update

import com.hierynomus.msdtyp.AccessMask
import com.hierynomus.mssmb2.SMB2CreateDisposition
import com.hierynomus.mssmb2.SMB2ShareAccess
import com.hierynomus.smbj.SMBClient
import com.hierynomus.smbj.auth.AuthenticationContext
import com.hierynomus.smbj.share.DiskShare
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.EnumSet

private const val MANIFEST_NAME = "latest.json"

/** Reads updates straight off the Synology SMB share. */
class SmbUpdateSource : UpdateSource {

    override suspend fun fetchManifest(cfg: UpdateConfig): UpdateManifest? =
        withContext(Dispatchers.IO) {
            withShare(cfg) { share ->
                val text = openRead(share, MANIFEST_NAME).use {
                    it.readBytes().toString(Charsets.UTF_8)
                }
                UpdateManifest.parse(text)
            }
        }

    override suspend fun downloadApk(
        cfg: UpdateConfig,
        name: String,
        target: File,
        onProgress: (Float) -> Unit,
    ) = withContext(Dispatchers.IO) {
        withShare(cfg) { share ->
            val total = runCatching {
                share.getFileInformation(name).standardInformation.endOfFile
            }.getOrDefault(0L)

            openRead(share, name).use { input ->
                target.outputStream().use { output ->
                    val buf = ByteArray(64 * 1024)
                    var copied = 0L
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        output.write(buf, 0, n)
                        copied += n
                        if (total > 0) onProgress(copied.toFloat() / total)
                    }
                }
            }
            onProgress(1f)
        }
    }

    private fun openRead(share: DiskShare, name: String) =
        share.openFile(
            name,
            EnumSet.of(AccessMask.GENERIC_READ),
            null,
            SMB2ShareAccess.ALL,
            SMB2CreateDisposition.FILE_OPEN,
            null,
        ).inputStream

    /** Connect, authenticate, run [block], always tear the connection down. */
    private fun <T> withShare(cfg: UpdateConfig, block: (DiskShare) -> T): T =
        SMBClient().connect(cfg.host).use { conn ->
            val session = conn.authenticate(
                AuthenticationContext(cfg.username, cfg.password.toCharArray(), null)
            )
            (session.connectShare(cfg.share) as DiskShare).use(block)
        }
}
```

- [ ] **Step 2: Over build**

```bash
cd /c/music && android/gradlew.bat -p android assembleDebug
```

Očakávaj: BUILD SUCCESSFUL.

- [ ] **Step 3: Commit**

```bash
cd /c/music && git add -A && git commit -m "feat(android): SMB update source"
```

---

### Task 7: Ukladanie nastavení

**Files:**
- Create: `android/app/src/main/java/sk/lanmusic/update/UpdateSettingsStore.kt`

- [ ] **Step 1: Implementuj**

```kotlin
package sk.lanmusic.update

import android.content.Context

private const val PREFS = "lanmusic_update"

/** Persists the NAS credentials in app-private storage. */
class UpdateSettingsStore(context: Context) {

    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun load(): UpdateConfig {
        val defaults = UpdateConfig()
        return UpdateConfig(
            host = prefs.getString("host", defaults.host) ?: defaults.host,
            share = prefs.getString("share", defaults.share) ?: defaults.share,
            username = prefs.getString("username", "") ?: "",
            password = prefs.getString("password", "") ?: "",
        )
    }

    fun save(cfg: UpdateConfig) {
        prefs.edit()
            .putString("host", cfg.host.trim())
            .putString("share", cfg.share.trim())
            .putString("username", cfg.username.trim())
            .putString("password", cfg.password)
            .apply()
    }
}
```

Heslo sa zámerne netrimuje — medzera môže byť jeho súčasťou.

- [ ] **Step 2: Commit**

```bash
cd /c/music && git add -A && git commit -m "feat(android): persist NAS update settings"
```

---

### Task 8: FileProvider a `ApkInstaller`

**Files:**
- Modify: `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/res/xml/file_paths.xml`
- Create: `android/app/src/main/java/sk/lanmusic/update/ApkInstaller.kt`

- [ ] **Step 1: Pridaj povolenie a provider do manifestu**

K existujúcim `uses-permission` (po `CHANGE_WIFI_MULTICAST_STATE`):

```xml
<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />
```

Dovnútra `<application>`, za `<service>`:

```xml
<provider
    android:name="androidx.core.content.FileProvider"
    android:authorities="${applicationId}.fileprovider"
    android:exported="false"
    android:grantUriPermissions="true">
    <meta-data
        android:name="android.support.FILE_PROVIDER_PATHS"
        android:resource="@xml/file_paths" />
</provider>
```

- [ ] **Step 2: Vytvor `res/xml/file_paths.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<paths>
    <cache-path name="updates" path="updates/" />
</paths>
```

`<cache-path>` zodpovedá `context.cacheDir` — presne tam `UpdateChecker` sťahuje. Ak sa tieto dve cesty rozídu, inštalátor spadne na `IllegalArgumentException: Failed to find configured root`.

- [ ] **Step 3: Implementuj `ApkInstaller`**

```kotlin
package sk.lanmusic.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File

private const val APK_MIME = "application/vnd.android.package-archive"

/** Hands a downloaded APK to the system installer. */
class ApkInstaller(private val context: Context) {

    /** Android 8+ requires per-app consent before it will open the installer. */
    fun canInstall(): Boolean =
        context.packageManager.canRequestPackageInstalls()

    /** Sends the user to the "allow from this source" settings screen. */
    fun requestPermission() {
        val intent = Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:${context.packageName}"),
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    fun install(file: File) {
        val uri = FileProvider.getUriForFile(
            context, "${context.packageName}.fileprovider", file,
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, APK_MIME)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }
}
```

- [ ] **Step 4: Over build a commitni**

```bash
cd /c/music && android/gradlew.bat -p android assembleDebug
cd /c/music && git add -A && git commit -m "feat(android): APK installer via FileProvider"
```

---

## Chunk 4: UI, podpisovanie a publikovanie

### Task 9: Napoj aktualizácie na ViewModel

**Files:**
- Modify: `android/app/src/main/java/sk/lanmusic/ui/PlayerViewModel.kt`

- [ ] **Step 1: Rozšír `PlayerUiState`**

Do data class pridaj:

```kotlin
val updateState: UpdateState = UpdateState.Idle,
val updateConfig: UpdateConfig = UpdateConfig(),
val appVersion: String = "",
```

Doimportuj `sk.lanmusic.update.*`.

- [ ] **Step 2: Priprav závislosti vo ViewModeli**

Za existujúce polia:

```kotlin
private val settingsStore = UpdateSettingsStore(application)
private val installer = ApkInstaller(application)
private val updateChecker = UpdateChecker(
    source = SmbUpdateSource(),
    cacheDir = application.cacheDir,
    currentVersionCode = { installedVersionCode(application) },
)
private var updateCheckJob: Job? = null
```

A pomocné funkcie na verziu — `longVersionCode` je API 28+, preto fallback:

```kotlin
@Suppress("DEPRECATION")
private fun installedVersionCode(app: Application): Long {
    val info = app.packageManager.getPackageInfo(app.packageName, 0)
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        info.longVersionCode
    } else {
        info.versionCode.toLong()
    }
}

private fun installedVersionName(app: Application): String =
    app.packageManager.getPackageInfo(app.packageName, 0).versionName ?: ""
```

Doimportuj `android.os.Build`.

- [ ] **Step 3: Spusti automatickú kontrolu pri štarte**

Do `init { }` bloku ViewModelu (ak neexistuje, vytvor ho za deklaráciami polí):

```kotlin
init {
    val app = getApplication<Application>()
    _uiState.update {
        it.copy(
            updateConfig = settingsStore.load(),
            appVersion = installedVersionName(app),
        )
    }
    viewModelScope.launch {
        updateChecker.state.collect { s ->
            _uiState.update { it.copy(updateState = s) }
        }
    }
    checkForUpdates(silent = true)
}
```

- [ ] **Step 4: Doplň akcie**

```kotlin
/**
 * @param silent startup check — errors stay in the log so an offline NAS
 *               never nags the user. Manual checks surface everything.
 */
fun checkForUpdates(silent: Boolean = false) {
    updateCheckJob?.cancel()
    updateCheckJob = viewModelScope.launch {
        val cfg = _uiState.value.updateConfig
        if (silent && !cfg.isComplete) return@launch
        updateChecker.check(cfg)
        if (silent && updateChecker.state.value is UpdateState.Failed) {
            updateChecker.reset()
        }
    }
}

fun onUpdateSettingsSaved(cfg: UpdateConfig) {
    settingsStore.save(cfg)
    _uiState.update { it.copy(updateConfig = cfg) }
}

/** Used by the "Otestovať spojenie" button; returns a message to display. */
suspend fun testConnection(cfg: UpdateConfig): String = try {
    val m = SmbUpdateSource().fetchManifest(cfg)
    if (m == null) "Spojenie OK, ale latest.json sa nedá prečítať."
    else "OK — na NASe je verzia ${m.versionName}."
} catch (e: Exception) {
    "Chyba: ${e.message ?: e::class.simpleName}"
}

fun onInstallUpdate() {
    val s = _uiState.value.updateState
    if (s !is UpdateState.ReadyToInstall) return
    if (!installer.canInstall()) {
        installer.requestPermission()
        return
    }
    installer.install(s.file)
}

fun onDismissUpdate() = updateChecker.reset()
```

- [ ] **Step 5: Over build a commitni**

```bash
cd /c/music && android/gradlew.bat -p android assembleDebug
cd /c/music && git add -A && git commit -m "feat(android): wire update checking into view model"
```

---

### Task 10: UI — menu, dialógy, nastavenia

**Files:**
- Modify: `android/app/src/main/java/sk/lanmusic/ui/PlayerScreen.kt`
- Modify: `android/app/src/main/java/sk/lanmusic/MainActivity.kt`

- [ ] **Step 1: Presuň ⋮ menu spred podmienky `isFound`**

Toto je oprava chyby nájdenej pri čítaní kódu, nie kozmetika. Dnes `PlayerScreen.kt:72` vykreslí celé menu len keď je nájdený **PC** server. NAS je od PC nezávislý — s vypnutým PC by sa používateľ nedostal k nastaveniam aktualizácií.

Nahraď `if (isFound) { Box { ... } }` za `Box { ... }` a podmieň len tie dve položky:

```kotlin
Box {
    IconButton(onClick = { menuExpanded = true }) {
        Icon(Icons.Filled.MoreVert, contentDescription = "Možnosti")
    }
    DropdownMenu(
        expanded = menuExpanded,
        onDismissRequest = { menuExpanded = false },
    ) {
        if (isFound) {
            DropdownMenuItem(
                text = { Text("Uspať PC") },
                onClick = { menuExpanded = false; pendingPowerAction = "sleep" },
            )
            DropdownMenuItem(
                text = { Text("Vypnúť PC", color = MaterialTheme.colorScheme.error) },
                onClick = { menuExpanded = false; pendingPowerAction = "shutdown" },
            )
            HorizontalDivider()
        }
        DropdownMenuItem(
            text = { Text("Verzia ${uiState.appVersion}", color = MaterialTheme.colorScheme.onSurfaceVariant) },
            onClick = {},
            enabled = false,
        )
        DropdownMenuItem(
            text = { Text("Skontrolovať aktualizácie") },
            onClick = { menuExpanded = false; onCheckUpdates() },
        )
        DropdownMenuItem(
            text = { Text("Nastavenia aktualizácií") },
            onClick = { menuExpanded = false; showUpdateSettings = true },
        )
    }
}
```

- [ ] **Step 2: Rozšír signatúru `PlayerScreen`**

```kotlin
onCheckUpdates: () -> Unit,
onInstallUpdate: () -> Unit,
onDismissUpdate: () -> Unit,
onSaveUpdateSettings: (UpdateConfig) -> Unit,
onTestConnection: suspend (UpdateConfig) -> String,
```

A lokálny stav vedľa `menuExpanded`:

```kotlin
var showUpdateSettings by remember { mutableStateOf(false) }
```

- [ ] **Step 3: Pridaj dialóg novej verzie**

Za existujúci `AlertDialog` pre power akcie (okolo riadku 199):

```kotlin
val update = uiState.updateState
if (update is UpdateState.ReadyToInstall) {
    AlertDialog(
        onDismissRequest = onDismissUpdate,
        title = { Text("Nová verzia ${update.manifest.versionName}") },
        text = {
            Column {
                Text("Je pripravená na inštaláciu.")
                if (update.manifest.notes.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    Text(update.manifest.notes, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        },
        confirmButton = { TextButton(onClick = onInstallUpdate) { Text("Inštalovať") } },
        dismissButton = { TextButton(onClick = onDismissUpdate) { Text("Neskôr") } },
    )
}
```

Stavy `Checking` / `Downloading` / `Failed` / `UpToDate` zámerne **nemajú** dialóg — pri tichej štartovej kontrole by otravovali. Zobrazí ich `showUpdateSettings` dialóg a snackbar pri manuálnej kontrole (Step 5).

- [ ] **Step 4: Pridaj dialóg nastavení**

Nový composable na koniec `PlayerScreen.kt`:

```kotlin
@Composable
private fun UpdateSettingsDialog(
    initial: UpdateConfig,
    onSave: (UpdateConfig) -> Unit,
    onTest: suspend (UpdateConfig) -> String,
    onDismiss: () -> Unit,
) {
    var host by remember { mutableStateOf(initial.host) }
    var share by remember { mutableStateOf(initial.share) }
    var user by remember { mutableStateOf(initial.username) }
    var pass by remember { mutableStateOf(initial.password) }
    var testResult by remember { mutableStateOf<String?>(null) }
    var testing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    val current = UpdateConfig(host, share, user, pass)

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Nastavenia aktualizácií") },
        text = {
            Column {
                OutlinedTextField(host, { host = it }, label = { Text("NAS adresa") }, singleLine = true)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(share, { share = it }, label = { Text("Share") }, singleLine = true)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(user, { user = it }, label = { Text("Meno") }, singleLine = true)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    pass, { pass = it }, label = { Text("Heslo") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
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
            TextButton(onClick = { onSave(current); onDismiss() }) { Text("Uložiť") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Zrušiť") } },
    )
}
```

Vykresli ho, keď `showUpdateSettings`. Doimportuj `androidx.compose.ui.text.input.PasswordVisualTransformation` a `kotlinx.coroutines.launch`.

- [ ] **Step 5: Spätná väzba pri manuálnej kontrole**

Manuálna kontrola musí niečo povedať aj keď je všetko v poriadku, inak to vyzerá pokazene. Pridaj `SnackbarHost` a reaguj na `UpToDate` / `Failed` / `NotConfigured`. Použi `LaunchedEffect(uiState.updateState)` a snackbar zobraz len ak kontrolu vyvolal používateľ — sleduj to lokálnym `var manualCheck by remember { mutableStateOf(false) }`, ktoré nastavíš v `onCheckUpdates`.

- [ ] **Step 6: Napoj v `MainActivity`**

Do volania `PlayerScreen(...)`:

```kotlin
onCheckUpdates = { viewModel.checkForUpdates() },
onInstallUpdate = viewModel::onInstallUpdate,
onDismissUpdate = viewModel::onDismissUpdate,
onSaveUpdateSettings = viewModel::onUpdateSettingsSaved,
onTestConnection = viewModel::testConnection,
```

- [ ] **Step 7: Over build a commitni**

```bash
cd /c/music && android/gradlew.bat -p android assembleDebug
cd /c/music && git add -A && git commit -m "feat(android): update UI — menu, dialogs, settings"
```

---

### Task 11: Release keystore a podpisovanie

**Files:**
- Create: `android/keystore/lanmusic.jks`
- Create: `android/keystore.properties`
- Modify: `android/app/build.gradle.kts`

- [ ] **Step 1: Vytvor keystore**

`keytool` je v JDK, ktoré používa Android Studio (`C:\Program Files\Android\Android Studio\jbr\bin`).

```bash
mkdir -p C:/music/android/keystore
keytool -genkeypair -v \
  -keystore C:/music/android/keystore/lanmusic.jks \
  -alias lanmusic -keyalg RSA -keysize 4096 -validity 10000 \
  -dname "CN=LAN Music, O=Home, C=SK"
```

Heslo si zvoľ a zapamätaj. **Tento súbor nikdy nestrácaj a nemeň** — bez neho sa už na existujúce inštalácie nedá vydať aktualizácia. Odzálohuj si ho mimo tohto PC.

- [ ] **Step 2: Vytvor `android/keystore.properties`**

```properties
storeFile=keystore/lanmusic.jks
storePassword=TVOJE_HESLO
keyAlias=lanmusic
keyPassword=TVOJE_HESLO
```

Tento súbor je v `.gitignore` z Task 0.

- [ ] **Step 3: Napoj do `build.gradle.kts`**

Úplne navrch súboru, nad `plugins { }`:

```kotlin
import java.util.Properties

val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) keystorePropsFile.inputStream().use { load(it) }
}
```

Do `android { }`, pred `buildTypes`:

```kotlin
signingConfigs {
    if (keystorePropsFile.exists()) {
        create("release") {
            storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
            storePassword = keystoreProps.getProperty("storePassword")
            keyAlias = keystoreProps.getProperty("keyAlias")
            keyPassword = keystoreProps.getProperty("keyPassword")
        }
    }
}
```

A v `buildTypes`:

```kotlin
release {
    isMinifyEnabled = false
    if (keystorePropsFile.exists()) {
        signingConfig = signingConfigs.getByName("release")
    }
}
```

Podmienka `exists()` drží build funkčný aj na stroji bez keystoru (spadne až `assembleRelease`, nie konfigurácia projektu).

- [ ] **Step 4: Zdvihni verziu**

V `defaultConfig`: `versionCode = 4`, `versionName = "1.3"`.

- [ ] **Step 5: Postav podpísaný release**

```bash
cd /c/music && android/gradlew.bat -p android assembleRelease
```

Očakávaj: BUILD SUCCESSFUL, APK v `android/app/build/outputs/apk/release/app-release.apk`.

- [ ] **Step 6: Over podpis**

```bash
cd /c/music && "C:/Users/<pouzivatel>/AppData/Local/Android/Sdk/build-tools/35.0.0/apksigner.bat" verify --print-certs android/app/build/outputs/apk/release/app-release.apk
```

Očakávaj: výpis certifikátu s `CN=LAN Music`. Ak hlási `DOES NOT VERIFY`, podpis sa nenapojil — skontroluj Step 3.

- [ ] **Step 7: Commit**

```bash
cd /c/music && git add -A && git commit -m "build(android): release signing config, bump to 1.3 (versionCode 4)"
```

Over, že `keystore.properties` ani `keystore/` v commite **nie sú** (`git status --ignored`).

---

### Task 12: `publish-apk.ps1`

**Files:**
- Create: `android/publish-apk.ps1`

- [ ] **Step 1: Napíš skript**

```powershell
# Publishes the signed release APK to the NAS share and rewrites latest.json.
# Usage:  .\publish-apk.ps1 [-Notes "co je nove"]
param(
    [string]$Notes = "",
    [string]$ShareRoot = "\\nas.local\Android"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- read version straight from the gradle file so it can never drift ---
$gradle = Get-Content "$root\app\build.gradle.kts" -Raw
if ($gradle -notmatch 'versionCode\s*=\s*(\d+)') { throw "versionCode not found in build.gradle.kts" }
$versionCode = [int]$Matches[1]
if ($gradle -notmatch 'versionName\s*=\s*"([^"]+)"') { throw "versionName not found in build.gradle.kts" }
$versionName = $Matches[1]

$apkSource = "$root\app\build\outputs\apk\release\app-release.apk"
if (-not (Test-Path $apkSource)) {
    throw "Release APK not found. Run: android\gradlew.bat -p android assembleRelease"
}

if (-not (Test-Path $ShareRoot)) { throw "NAS share not reachable: $ShareRoot" }

# --- refuse to publish a version the phone would ignore ---
$manifestPath = Join-Path $ShareRoot "latest.json"
if (Test-Path $manifestPath) {
    $existing = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if ($versionCode -le $existing.versionCode) {
        throw ("versionCode $versionCode is not greater than the published " +
               "$($existing.versionCode). Bump versionCode in build.gradle.kts, " +
               "otherwise phones will never see this build.")
    }
}

$apkName = "lanmusic-$versionName.apk"
$apkTarget = Join-Path $ShareRoot $apkName

Write-Host "Copying $apkName ..."
Copy-Item $apkSource $apkTarget -Force

$sha = (Get-FileHash $apkTarget -Algorithm SHA256).Hash.ToLower()

# Write the manifest last: until it points at the new APK, phones keep the old one.
[ordered]@{
    versionCode = $versionCode
    versionName = $versionName
    apk         = $apkName
    sha256      = $sha
    notes       = $Notes
} | ConvertTo-Json | Set-Content $manifestPath -Encoding UTF8

Write-Host "Published $versionName (versionCode $versionCode)" -ForegroundColor Green
Write-Host "  sha256 $sha"
```

Dve veci, ktoré sú v skripte zámerne:
- **Verzia sa číta z `build.gradle.kts`**, nezadáva sa ručne — `latest.json` sa nemôže rozísť s APK.
- **`latest.json` sa píše až po skopírovaní APK.** Keby to bolo opačne, telefón by v okne medzi zápismi videl manifest ukazujúci na neexistujúci alebo nedokončený súbor.

- [ ] **Step 2: Spusti**

```powershell
cd C:\music\android; .\publish-apk.ps1 -Notes "Automaticke aktualizacie z NASu"
```

Očakávaj: zelené `Published 1.3 (versionCode 4)`.

Ak hlási, že share nie je dostupný, priprav si prihlásenie: `net use \\nas.local\Android /user:nasuser`.

- [ ] **Step 3: Over obsah share-u**

Na NASe musí byť `lanmusic-1.3.apk` a `latest.json` s `versionCode: 4` a nenulovým `sha256`.

- [ ] **Step 4: Commit**

```bash
cd /c/music && git add -A && git commit -m "build(android): publish script for NAS releases"
```

---

### Task 13: Overenie na zariadení

Bez tohto tasku je feature len nádej. SMB, FileProvider aj inštalačný intent sa dajú overiť jedine na reálnom telefóne.

- [ ] **Step 1: Odinštaluj starú appku**

Debug podpis ≠ nový release podpis, takže inštalácia „cez" starú zlyhá. Toto je jednorazové.

```bash
adb uninstall sk.lanmusic
```

- [ ] **Step 2: Nainštaluj release build**

```bash
adb install C:/music/android/app/build/outputs/apk/release/app-release.apk
```

- [ ] **Step 3: Nastav a otestuj spojenie**

Spusti appku → ⋮ → *Nastavenia aktualizácií* → zadaj meno a heslo → *Otestovať spojenie*.

Očakávaj: `OK — na NASe je verzia 1.3.`

- [ ] **Step 4: Over „žiadna aktualizácia"**

⋮ → *Skontrolovať aktualizácie*. Nainštalovaná verzia je 4, na NASe tiež 4 → očakávaj hlásenie, že si aktuálny. **Žiadny** dialóg o novej verzii.

- [ ] **Step 5: Otestuj skutočný update — toto je ten dôležitý test**

1. V `build.gradle.kts` zmeň na `versionCode = 5`, `versionName = "1.4"`.
2. `android/gradlew.bat -p android assembleRelease`
3. `cd C:\music\android; .\publish-apk.ps1 -Notes "Test aktualizacie"`
4. Na telefóne appku úplne zavri a znova spusti.

Očakávaj: po pár sekundách dialóg *Nová verzia 1.4*. Ťukni **Inštalovať**.

- Ak Android vypýta povolenie inštalovať z tohto zdroja → povoľ a ťukni Inštalovať znova.
- Očakávaj systémový inštalátor a **úspešnú** inštaláciu.
- Po spustení ⋮ → *Verzia 1.4*.

**Ak inštalátor hlási „App not installed"** → podpisy sa nezhodujú. Znamená to, že si niektorý build spravil debug podpisom. Postav oba z rovnakej `signingConfig`.

- [ ] **Step 6: Over správanie mimo NASu**

Vypni WiFi (alebo prejdi na mobilné dáta) a spusti appku.

Očakávaj: appka nabehne normálne, **žiadna** chybová hláška o aktualizáciách. Tichá štartová kontrola nesmie používateľa otravovať. Manuálna kontrola z menu naopak chybu ukázať má.

- [ ] **Step 7: Regresia — prehrávanie musí fungovať**

Zapni PC prehrávač a over, že discovery, transport, playlist aj streaming fungujú ako pred zmenou. Zdvihnutie `minSdk` a nová závislosť by sa ich dotknúť nemali, ale toto je jediný spôsob, ako to vieš.

- [ ] **Step 8: Spusti všetky JVM testy naposledy**

```bash
cd /c/music && android/gradlew.bat -p android testDebugUnitTest
```

Očakávaj: PASS, 20 testov.

- [ ] **Step 9: Commit**

```bash
cd /c/music && git add -A && git commit -m "test(android): verified self-update end to end"
```

---

## Definition of done

- [ ] `gradlew -p android testDebugUnitTest` prejde (20 testov)
- [ ] `assembleRelease` vyrobí APK podpísané `lanmusic.jks` (overené `apksigner verify`)
- [ ] Appka ukazuje aktuálnu verziu v ⋮ menu
- [ ] *Otestovať spojenie* rozlíši úspech, zlé heslo a nedostupný NAS
- [ ] Skutočná aktualizácia 1.3 → 1.4 prešla na zariadení vrátane inštalácie
- [ ] Bez dosahu na NAS appka nabehne ticho, bez chýb
- [ ] Prehrávanie, discovery a remote control fungujú ako predtým
- [ ] `keystore.properties` ani `keystore/` nie sú vo verzovaní
- [ ] `publish-apk.ps1` odmietne publikovať nezvýšený `versionCode`
