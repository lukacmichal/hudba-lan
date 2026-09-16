package sk.lanmusic.service

sealed class PlaybackState {
    object Playing : PlaybackState()
    object Connecting : PlaybackState()
    object Stopped : PlaybackState()
    object Error : PlaybackState()
}
