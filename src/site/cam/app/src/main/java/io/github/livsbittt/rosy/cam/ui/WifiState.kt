package io.github.livsbittt.rosy.cam.ui

import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import java.net.Inet4Address

/** [LanSnapshot] of one network's LinkProperties. */
fun lanSnapshot(properties: LinkProperties): LanSnapshot = LanSnapshot.from(
    properties.linkAddresses.map { it.address to it.prefixLength },
    properties.routes.firstOrNull { it.isDefaultRoute && it.gateway is Inet4Address }?.gateway,
)

private fun ConnectivityManager.isLan(network: Network): Boolean {
    val caps = getNetworkCapabilities(network) ?: return false
    return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
}

/**
 * The first Wi-Fi/Ethernet network that holds a usable address right now, whether or not it is the default
 * network: a closed site Wi-Fi without internet often loses "default" to mobile data.
 */
@Suppress("DEPRECATION")
fun ConnectivityManager.currentLan(): LanSnapshot? = allNetworks.asSequence()
    .filter { isLan(it) }
    .mapNotNull { network -> getLinkProperties(network)?.let(::lanSnapshot) }
    .firstOrNull { it.connected }

/** [currentLan] kept up to date from network callbacks; null while no LAN network has an address. */
@Composable
fun rememberLan(): LanSnapshot? {
    val context = LocalContext.current
    val connectivity = remember(context) { context.getSystemService(ConnectivityManager::class.java) }
    val lan = remember { LanNetworks() }
    var current by remember { mutableStateOf(connectivity.currentLan()) }
    DisposableEffect(connectivity) {
        // Transports are OR-ed; dropping INTERNET keeps a no-internet site Wi-Fi in the request.
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                lan.onAvailable(network.toString())
                // Seed from what the network already has, so the state never flips to "no Wi-Fi" while
                // waiting for onLinkPropertiesChanged (review m7).
                connectivity.getLinkProperties(network)?.let { lan.onLinkProperties(network.toString(), lanSnapshot(it)) }
                current = lan.current()
            }

            override fun onLinkPropertiesChanged(network: Network, linkProperties: LinkProperties) {
                lan.onLinkProperties(network.toString(), lanSnapshot(linkProperties))
                current = lan.current()
            }

            override fun onLost(network: Network) {
                lan.onLost(network.toString())
                current = lan.current()
            }
        }
        connectivity.registerNetworkCallback(request, callback)
        onDispose { connectivity.unregisterNetworkCallback(callback) }
    }
    return current
}
