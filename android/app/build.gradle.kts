import java.util.Properties

// Release signing must use a stable key: Android only installs an update when
// it is signed with the same key as the installed app.
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) keystorePropsFile.inputStream().use { load(it) }
}

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// ---- spolocny blok pre vsetky appky (nemen len tu, viz docs/shared-standard.md) ----
/**
 * Pristupove udaje k NAS-u sa citaju z JEDNEHO suboru spolocneho pre vsetky
 * appky: nas-credentials.local. Odtial sa pri builde vlozia do APK ako
 * predvolby, takze na telefone sa uz nic nezadava.
 *
 * Prepis v Nastaveniach appky ma prednost — to je cesta pre zmenu hesla bez
 * rebuildu. Ked subor chyba, hodnoty ostanu prazdne a appka si udaje vypyta
 * v Nastaveniach ako predtym; build kvoli tomu nikdy nespadne.
 *
 * Heslo timto konci v APK. Je to vedome rozhodnutie: APK lezia na tom istom
 * NAS-e pod tym istym uctom, takze kto sa dostane k nim, ten ucet uz ma.
 */
fun nasSetting(key: String): String {
    val f = file(System.getenv("NAS_CREDENTIALS") ?: "nas-credentials.local")
    if (!f.exists()) return ""
    return f.readLines()
        .firstOrNull { it.trimStart().startsWith("$key=") }
        ?.substringAfter("=")?.trim().orEmpty()
}

/** Heslo moze obsahovat spatne lomitko aj uvodzovku — bez tohto by build nepreslo. */
fun nasField(key: String): String =
    "\"" + nasSetting(key).replace("\\", "\\\\").replace("\"", "\\\"") + "\""
// ---- koniec spolocneho bloku -------------------------------------------------

android {
    namespace = "sk.lanmusic"
    compileSdk = 35

    defaultConfig {
        applicationId = "sk.lanmusic"
        minSdk = 26
        targetSdk = 35
        // 1.3.4: shared version footer; the APK is only downloaded after a yes.
        // 1.4.0 (16. 8. 2026): vyhľadávanie v playliste a posuvník vedľa neho
        // (v dlhom playliste sa inak nedalo pohnúť), a obrazovka „server
        // nedostupný" už neblikoce so spinnerom a hovorí, že aktualizácia
        // appky funguje aj s vypnutým PC.
        // 1.8 (31. 8. 2026): v ⋮ pribudol „Spánok 2" — PC pustí skladby zo
        // svojho zoznamu spanok2.m3u a po dohratí sa uspí/vypne ako pri
        // „Spánok". Zoznam aj to, či sa playlist vráti do pôvodného stavu,
        // sa nastavuje v prehrávači na PC.
        // 1.9 (31. 8. 2026): widget ma dva riadky — vlavo hore skladba,
        // vpravo hore uspat / Spánok 2 / vypnút, dole prehrávanie cez celú šírku.
        // 2.0 (31. 8. 2026): vo widgete pribudol Spánok (dohrajú posledné tri
        // skladby) — vlavo od ostatných troch, aby si nezmenili polohu.
        // Pozor: potrebuje PC prehrávač, ktorý pozná API akciu `spanok`.
        // 2.1 (1. 9. 2026): kapela je nad názvom skladby a väčším písmom (aj
        // v hlavičke, aj v riadkoch playlistu). Zoznam je zhustený tak, aby sa
        // na obrazovku zmestilo zhruba dvojnásobok skladieb.
        // 2.2 (1. 9. 2026): dalsie zhustenie — "Ukončiť" sa presunulo do ⋮
        // (samostatné tlačidlo nad pätičkou bralo 48dp) a horné ikony sú 36dp
        // namiesto 48dp. Pätička s verziou ostáva podľa docs/shared-standard.md 2.6.
        // 2.3 (1. 9. 2026): čas je nad posuvníkom a posuvník nižší; tlačidlo
        // streamingu je užšie a vpravo vedľa neho sa vrátilo "Ukončiť" — už
        // nestojí vlastný riadok, takže je zase na očiach zadarmo.
        // 2.4 (1. 9. 2026): kapela a názov skladby sú na jednom riadku vedľa
        // seba — nad sebou brali dva riadky, hoci voľné miesto bolo vodorovné.
        // 2.5 (1. 9. 2026): kapela a skladba sú zase nad sebou (jeden riadok
        // vedľa seba sa neosvedčil — orezávalo to mená). Čas sa presunul do
        // riadku s ovládacími tlačidlami: uplynutý vľavo, dĺžka vpravo.
        // Vydanie 3. 9. 2026: pocitadlo prenesenych dat rozdelene na Wi-Fi
        // a mobilne (Prenos.kt, spolocny subor) a sirsi rozsah velkosti
        // pisma (-6 az +6 namiesto -1 az +3).
        // 2.7 (25) — do pocitadla dat sa rata aj PRUD HUDBY (LibVLC
        // stats.readBytes); bez neho ukazovalo kilobajty tam, kde islo
        // o desiatky megabajtov.
        // 2.9 (28) — vo widgete riadok hlasitosti: tichsie / cislo / hlasnejsie
        // po 5, tuknutie na cislo stlmi. Na PC ten isty `setVolume` ako posuvnik.
        // 2.10 (29) — z tlacidiel −/+ je PAS: tuknes kam chces a hlasitost
        // je tam (20 dielikov po 5 %). Skutocny posuvnik widget mat nemoze,
        // `RemoteViews` SeekBar nepoznaju a tahanie berie launcher sebe.
        versionCode = 29
        versionName = "2.10"

        buildConfigField("String", "NAS_HOST", nasField("NAS_HOST"))
        buildConfigField("String", "NAS_SHARE", nasField("NAS_SHARE"))
        buildConfigField("String", "NAS_USER", nasField("NAS_USER"))
        buildConfigField("String", "NAS_PASS", nasField("NAS_PASS"))

        ndk {
            // LibVLC ships native libs for four ABIs, which is most of the APK.
            // x86/x86_64 are emulator-only and armeabi-v7a targets 32-bit phones
            // predating 2016 — none of which this app runs on. Keeping only
            // arm64-v8a cuts the download that self-update pulls on every
            // release from 187 MB to roughly 46 MB.
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        // Guarded so the project still configures on a machine without the
        // keystore; only assembleRelease fails there.
        if (keystorePropsFile.exists()) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystorePropsFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }

    // Ship a recognisable filename instead of the generic app-release.apk —
    // this file gets copied to the NAS and sideloaded by hand.
    applicationVariants.all {
        outputs.all {
            (this as com.android.build.gradle.internal.api.BaseVariantOutputImpl)
                .outputFileName = "metalmusic-$versionName.apk"
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.material3)
    implementation(libs.libvlc)
    implementation(libs.androidx.media)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.smbj)
    // smbj logs through slf4j; without a binding it spams logcat on every call.
    implementation(libs.slf4j.nop)
    // Encrypted prefs for the NAS password; master key lives in Android Keystore.
    implementation(libs.androidx.security.crypto)

    testImplementation("junit:junit:4.13.2")
    // Android's built-in org.json is a throwing stub under JVM unit tests;
    // this puts a real implementation on the test classpath.
    testImplementation("org.json:json:20240303")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
}
