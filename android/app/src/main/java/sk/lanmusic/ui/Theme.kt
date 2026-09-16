package sk.lanmusic.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import sk.lanmusic.Vzhlad

// Paleta Windows appky (music_player/ui.py) — Android klient ju zrkadlí,
// aby obe appky vyzerali rovnako.
val MetalBg = Color(0xFF1E1A16)            // _C_BG_HEADER
val MetalAccent = Color(0xFFD4860A)        // _C_ACCENT
val MetalAccentLight = Color(0xFFF0B44C)   // _C_ACCENT_LIGHT
val MetalTextPrimary = Color(0xFFF5EAD1)   // _C_TEXT_PRIMARY
val MetalTextSecondary = Color(0xFFA08060) // _C_TEXT_SECONDARY
val MetalSurface = Color(0xFF2B2520)       // _C_SURFACE
val MetalBorder = Color(0xFF3D3025)        // _C_BORDER
val MetalButton = Color(0xFF6B5C4E)        // QPushButton background
val MetalButtonBorder = Color(0xFF8A7A6A)  // QPushButton border

private val MetalColorScheme = darkColorScheme(
    primary = MetalAccent,
    onPrimary = MetalBg,
    primaryContainer = MetalAccent,
    onPrimaryContainer = MetalBg,
    secondary = MetalTextSecondary,
    onSecondary = MetalBg,
    secondaryContainer = MetalButton,
    onSecondaryContainer = MetalTextPrimary,
    tertiary = MetalAccentLight,
    onTertiary = MetalBg,
    background = MetalBg,
    onBackground = MetalTextPrimary,
    surface = MetalBg,
    onSurface = MetalTextPrimary,
    surfaceVariant = MetalSurface,
    onSurfaceVariant = MetalTextSecondary,
    surfaceContainer = MetalSurface,           // DropdownMenu
    surfaceContainerHigh = Color(0xFF3A3028),  // AlertDialog
    surfaceContainerHighest = Color(0xFF3D3028), // neaktívna dráha slidera
    outline = MetalButtonBorder,
    outlineVariant = MetalBorder,
    error = Color(0xFFE53935),
)

/**
 * Cierna varianta tej istej palety.
 *
 * Nie je to iny vzhlad — jantar, text aj okraje ostavaju rovnake. Meni sa len
 * to, co zabera najviac plochy: pozadie ide z #1E1A16 na cistu ciernu. Na OLED
 * displeji sa cierny pixel nerozsvieti vobec, kym #1E1A16 svieti takmer ako
 * svetly, takze prehravac otvoreny cely vecer stoji citelne menej baterie.
 * Karty a dialogy ostavaju o kusok nad ciernou, aby bolo vidiet ich hranicu.
 */
private val CiernaSchema = MetalColorScheme.copy(
    background = Color(0xFF000000),
    surface = Color(0xFF000000),
    surfaceVariant = Color(0xFF16120F),
    surfaceContainer = Color(0xFF16120F),
    surfaceContainerHigh = Color(0xFF1E1A16),
    surfaceContainerHighest = Color(0xFF241F1A),
)

/**
 * Cierny rezim sa berie z [Vzhlad], nie z `isSystemInDarkTheme()`: appka je
 * tmava vzdy a otazka neznie "je telefon v tmavom rezime", ale "chcem to
 * cierne kvoli baterke". Pri volbe "podla systemu" na to [Vzhlad.jeTmavy]
 * odpovie podla telefonu.
 */
@Composable
fun MetalTheme(content: @Composable () -> Unit) {
    val cierny = Vzhlad.jeTmavy(LocalContext.current)
    MaterialTheme(
        colorScheme = if (cierny) CiernaSchema else MetalColorScheme,
        content = content,
    )
}
