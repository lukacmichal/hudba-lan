package sk.lanmusic.ui

import android.content.Context
import android.os.Build
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import sk.lanmusic.R

/**
 * Pätička s verziou — jediný prvok, ktorý vyzerá ROVNAKO vo všetkých appkách
 * (docs/shared-standard.md, kapitola 2.6):
 *
 *     Metal Music 1.3.4 (8) · NAS 1.3.4 (8)
 *
 * Vždy úplne dole na hlavnej obrazovke, 11sp, tlmená farba, centrované.
 * Ťuknutím sa spustí ručná kontrola.
 *
 * Keď sa verzia na NAS-e nedala zistiť (mimo domu, NAS vypnutý), je tam
 * pomlčka — nie prázdno. Prázdne miesto vyzerá ako chyba vykreslenia,
 * pomlčka hovorí „pozrelo sa a nedalo sa zistiť".
 *
 * Rozmery aj farby sú zámerne rovnaké ako v XML variante appiek postavených
 * na klasických View-och; preto tu nie je `MaterialTheme` odtieň pre zvýraznenie,
 * ale ten istý jantár, aký majú ony v `colors.xml`.
 */
@Composable
fun VersionFooter(
    remote: String?,
    newer: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val ctx = LocalContext.current
    val warn = if (isSystemInDarkTheme()) Color(0xFFFBBF24) else Color(0xFFB45309)
    Text(
        text = buildString {
            append(ctx.getString(R.string.app_name))
            append(' ')
            append(installedVersion(ctx))
            append(" · NAS ")
            append(remote ?: "—")
            if (newer) append(" ↑")
        },
        fontSize = 11.sp,
        textAlign = TextAlign.Center,
        color = if (newer) warn else MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp),
    )
}

/** "1.3.4 (8)" — tvar, v ktorom sa verzia ukazuje všade. */
fun installedVersion(ctx: Context): String {
    val info = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
    val code = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        info.longVersionCode
    } else {
        @Suppress("DEPRECATION")
        info.versionCode.toLong()
    }
    return "${info.versionName ?: "?"} ($code)"
}
