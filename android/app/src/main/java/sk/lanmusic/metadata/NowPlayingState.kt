package sk.lanmusic.metadata

data class NowPlayingState(
    val title: String = "",
    val artist: String = "",
    val state: String = "stopped",
    val streamingActive: Boolean = false,
    val streamUrl: String = "",
    val positionMs: Long = 0,
    val durationMs: Long = 0,
    val currentIndex: Int = -1,
    val playlistVersion: Int = 0,
    val volume: Int = 50,
)
