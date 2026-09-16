package sk.lanmusic.discovery

sealed class DiscoveryState {
    object Discovering : DiscoveryState()
    data class Found(val ip: String, val port: Int) : DiscoveryState()
    object NotFound : DiscoveryState()
}
