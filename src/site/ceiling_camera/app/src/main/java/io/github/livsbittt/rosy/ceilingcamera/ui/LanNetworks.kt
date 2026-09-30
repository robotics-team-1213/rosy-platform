package io.github.livsbittt.rosy.overhead.ui

/** Wi-Fi/Ethernet networks currently up, keyed by network id. Pure JVM. */
class LanNetworks {
    private val up = mutableSetOf<String>()

    /** @return whether any LAN network is up after this change. */
    fun onAvailable(id: String): Boolean {
        up += id
        return up.isNotEmpty()
    }

    /** @return whether any LAN network is still up after this one is lost. */
    fun onLost(id: String): Boolean {
        up -= id
        return up.isNotEmpty()
    }
}
