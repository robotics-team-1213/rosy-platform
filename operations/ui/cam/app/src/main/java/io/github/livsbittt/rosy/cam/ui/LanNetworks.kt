package io.github.livsbittt.rosy.cam.ui

import java.net.Inet4Address
import java.net.InetAddress

/**
 * What one Wi-Fi/Ethernet network really has, from its LinkProperties: the IPv4 subnet and gateway.
 * A network counts as connected only when it holds a usable address, not when the Wi-Fi icon is on
 * (associated but no DHCP lease yet, or a captive AP that never handed one out). Pure JVM.
 */
data class LanSnapshot(val subnet: String?, val gateway: String?, val address: String?) {
    val connected: Boolean get() = address != null

    companion object {
        /**
         * @param addresses the link's addresses with their prefix lengths.
         * @param gateway the IPv4 default route's gateway, if any.
         */
        fun from(addresses: List<Pair<InetAddress, Int>>, gateway: InetAddress?): LanSnapshot {
            val v4 = addresses.firstOrNull { (a, _) -> a is Inet4Address && !a.isLinkLocalAddress && !a.isLoopbackAddress }
            val routableV6 = addresses.firstOrNull { (a, _) -> a !is Inet4Address && !a.isLinkLocalAddress && !a.isLoopbackAddress }
            return LanSnapshot(
                subnet = v4?.let { (a, prefix) -> subnetOf(a, prefix) },
                gateway = (gateway as? Inet4Address)?.hostAddress,
                address = (v4 ?: routableV6)?.first?.hostAddress,
            )
        }

        /** `192.168.1.0/24` for 192.168.1.37 with prefix 24. */
        fun subnetOf(address: InetAddress, prefix: Int): String? {
            if (address !is Inet4Address || prefix !in 0..32) return null
            val bits = address.address.fold(0L) { acc, b -> (acc shl 8) or (b.toLong() and 0xFF) }
            val mask = if (prefix == 0) 0L else (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
            val net = bits and mask
            return "${(net shr 24) and 0xFF}.${(net shr 16) and 0xFF}.${(net shr 8) and 0xFF}.${net and 0xFF}/$prefix"
        }
    }
}

/** Wi-Fi/Ethernet networks currently up, keyed by network id, with what each one has. Pure JVM. */
class LanNetworks {
    private val up = linkedMapOf<String, LanSnapshot?>()

    fun onAvailable(id: String) {
        if (id !in up) up[id] = null
    }

    fun onLinkProperties(id: String, snapshot: LanSnapshot) {
        up[id] = snapshot
    }

    fun onLost(id: String) {
        up -= id
    }

    /** The first network that holds a usable address, or null when none does. */
    fun current(): LanSnapshot? = up.values.firstOrNull { it?.connected == true }
}
