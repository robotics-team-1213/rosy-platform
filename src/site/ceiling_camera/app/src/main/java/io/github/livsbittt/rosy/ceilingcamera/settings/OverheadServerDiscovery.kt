package io.github.livsbittt.rosy.overhead.settings

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.os.Handler
import android.os.Looper
import java.util.concurrent.atomic.AtomicBoolean

/** Short-lived DNS-SD lookup for receiver and CORE endpoints on the current Wi-Fi LAN. */
class OverheadServerDiscovery(
    context: Context,
    private val onRecords: (List<OverheadServiceRecord>, List<RobotCoreServiceRecord>, Boolean, Boolean) -> Unit,
) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val main = Handler(Looper.getMainLooper())
    private val finished = AtomicBoolean(false)
    private val overhead = linkedMapOf<String, OverheadServiceRecord>()
    private val cores = linkedMapOf<String, RobotCoreServiceRecord>()
    private val listeners = mutableListOf<Pair<String, NsdManager.DiscoveryListener>>()
    private var lock: WifiManager.MulticastLock? = null
    private var wifiConnected = false

    fun start() {
        if (finished.get()) return
        wifiConnected = connectivity.activeNetwork?.let(connectivity::getNetworkCapabilities)
            ?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        if (!wifiConnected) {
            finished.set(true)
            publish(scanning = false)
            return
        }
        runCatching {
            wifi.createMulticastLock("rosy-overhead-mdns").apply {
                setReferenceCounted(false)
                acquire()
                lock = this
            }
        }
        discover(OverheadServiceRecord.SERVICE_TYPE)
        discover(RobotCoreServiceRecord.SERVICE_TYPE)
        main.postDelayed({ stop() }, SCAN_TIMEOUT_MS)
        publish(scanning = true)
    }

    fun stop() {
        if (!finished.compareAndSet(false, true)) return
        listeners.forEach { (_, listener) -> runCatching { nsd.stopServiceDiscovery(listener) } }
        listeners.clear()
        runCatching { lock?.let { if (it.isHeld) it.release() } }
        lock = null
        publish(scanning = false)
    }

    private fun discover(type: String) {
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) = Unit
            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (normalizeServiceType(serviceInfo.serviceType) != normalizeServiceType(type)) return
                @Suppress("DEPRECATION")
                nsd.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) = Unit
                    override fun onServiceResolved(info: NsdServiceInfo) {
                        if (finished.get()) return
                        when (type) {
                            OverheadServiceRecord.SERVICE_TYPE -> OverheadServiceRecord.parse(info)?.let {
                                overhead["${it.name}|${it.tlsHost}|${it.port}"] = it
                            }
                            RobotCoreServiceRecord.SERVICE_TYPE -> RobotCoreServiceRecord.parse(info)?.let {
                                cores["${it.name}|${it.host}|${it.port}"] = it
                            }
                        }
                        publish(scanning = true)
                    }
                })
            }
            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                overhead.entries.removeAll { it.value.name == serviceInfo.serviceName }
                cores.entries.removeAll { it.value.name == serviceInfo.serviceName }
                publish(scanning = true)
            }
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                runCatching { nsd.stopServiceDiscovery(this) }
            }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                runCatching { nsd.stopServiceDiscovery(this) }
            }
            override fun onDiscoveryStopped(serviceType: String) = Unit
        }
        listeners += type to listener
        runCatching { nsd.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, listener) }
            .onFailure { publish(scanning = true) }
    }

    private fun publish(scanning: Boolean) {
        main.post { onRecords(overhead.values.toList(), cores.values.toList(), scanning, wifiConnected) }
    }

    companion object { private const val SCAN_TIMEOUT_MS = 18_000L }
}
