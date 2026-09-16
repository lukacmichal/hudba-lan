package sk.lanmusic.playlist

import java.text.Normalizer
import java.util.Locale

/**
 * Vyhľadávanie v playliste.
 *
 * Bez diakritiky a bez ohľadu na veľkosť písmen — v metalovom playliste sú
 * názvy ako „Mörk Gryning" alebo „Ensiferum – Táhle", ktoré sa na telefóne
 * nedajú napísať presne, a hľadanie, ktoré si na tom zakladá, je horšie než
 * žiadne.
 *
 * Hľadá sa **v každom slove dopytu zvlášť** a naprieč interpretom aj názvom:
 * „opeth blackwater" nájde „Opeth — Blackwater Park" bez ohľadu na to, v akom
 * poradí to používateľ napíše.
 */
object PlaylistFilter {

    /** Malé písmená, bez diakritiky — porovnávací tvar. */
    fun normalize(s: String): String =
        Normalizer.normalize(s, Normalizer.Form.NFD)
            .replace(DIACRITICS, "")
            .lowercase(Locale.ROOT)

    fun matches(item: PlaylistItem, query: String): Boolean {
        val terms = normalize(query).split(' ').filter { it.isNotBlank() }
        if (terms.isEmpty()) return true
        val haystack = normalize("${item.artist} ${item.title}")
        return terms.all { haystack.contains(it) }
    }

    /**
     * Playlist zúžený na dopyt. Prázdny dopyt vracia pôvodný zoznam — teda
     * TÚ ISTÚ inštanciu, nech sa pri každom prekreslení nekopíruje playlist
     * o tisícoch položiek.
     *
     * Poradie ani indexy sa nemenia: `PlaylistItem.index` je poradie na
     * serveri a prehrávanie sa spúšťa podľa neho, nie podľa pozície
     * vo filtrovanom zozname.
     */
    fun filter(items: List<PlaylistItem>, query: String): List<PlaylistItem> {
        if (query.isBlank()) return items
        return items.filter { matches(it, query) }
    }

    private val DIACRITICS = Regex("\\p{Mn}+")
}
