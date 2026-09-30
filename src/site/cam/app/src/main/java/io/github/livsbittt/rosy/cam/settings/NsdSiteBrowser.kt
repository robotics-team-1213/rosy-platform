package io.github.livsbittt.rosy.cam.settings

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.util.Log
import io.github.livsbittt.rosy.cam.link.SiteBrowser
import io.github.livsbittt.rosy.cam.link.SiteSighting
import java.net.Inet4Address
import java.net.InetAddress
import java.util.concurrent.Executors

/**
 * [SiteBrowser] over Android NSD for the site link's re-discovery (D-391 1, D-341 13). Each call is one short
 * browse of `_rosy-overhead._tcp` under a multicast lock.
 *
 * NSD limits handled here:
 * - Before API 34, `resolveService` allows one resolve at a time per app (FAILURE_ALREADY_ACTIVE), so
 *   found services are resolved one after another.
 * - On API 34+, `registerServiceInfoCallback` replaces it: several services at once, all addresses
 *   (`hostAddresses`), and updates while the browse lasts.
 */
class NsdSiteBrowser(context: Context) : SiteBrowser {
    private val app = context.applicationContext
    private val nsd = app.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val wifi = app.getSystemService(Context.WIFI_SERVICE) as WifiManager

    override fun browse(timeoutMs: Long, match: (SiteSighting) -> Boolean): List<SiteSighting> {
        val session = Session(match)
        val lock = runCatching {
            wifi.createMulticastLock("rosy-site-link").apply {
                setReferenceCounted(false)
                acquire()
            }
        }.getOrNull()
        try {
            session.start()
            val start = now()
            var end = start + timeoutMs
            while (now() < end) {
                session.firstMatchAt()?.let { end = minOf(end, it + SETTLE_MS) }
                Thread.sleep(POLL_MS)
            }
        } finally {
            session.stop()
            runCatching { lock?.let { if (it.isHeld) it.release() } }
        }
        return session.matches()
    }

    /** One browse: discovery listener, resolves, and the matches by service name. */
    private inner class Session(private val match: (SiteSighting) -> Boolean) {
        private val guard = Any()
        private val executor = Executors.newSingleThreadExecutor()
        private val byService = linkedMapOf<String, SiteSighting>()
        private val pending = ArrayDeque<NsdServiceInfo>()
        private val callbacks = mutableListOf<Any>()
        private var resolving = false
        private var stopped = false
        private var firstMatchAt: Long? = null

        private val discovery = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) = Unit
            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (normalizeServiceType(serviceInfo.serviceType) != normalizeServiceType(OverheadServiceRecord.SERVICE_TYPE)) return
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) watch(serviceInfo) else enqueue(serviceInfo)
            }
            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                synchronized(guard) { byService.remove(serviceInfo.serviceName) }
            }
            override fun onDiscoveryStopped(serviceType: String) = Unit
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "discovery failed to start: $errorCode")
            }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
        }

        fun start() {
            runCatching { nsd.discoverServices(OverheadServiceRecord.SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discovery) }
                .onFailure { Log.w(TAG, "discoverServices failed", it) }
        }

        fun stop() {
            val watched = synchronized(guard) {
                stopped = true
                pending.clear()
                callbacks.toList().also { callbacks.clear() }
            }
            runCatching { nsd.stopServiceDiscovery(discovery) }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                watched.forEach { cb -> runCatching { nsd.unregisterServiceInfoCallback(cb as NsdManager.ServiceInfoCallback) } }
            }
            executor.shutdown()
        }

        fun firstMatchAt(): Long? = synchronized(guard) { firstMatchAt }

        fun matches(): List<SiteSighting> = synchronized(guard) { byService.values.filter(match) }

        private fun record(info: NsdServiceInfo, addresses: List<InetAddress>) {
            val parsed = OverheadServiceRecord.parse(info) ?: return
            if (addresses.isEmpty()) return
            // IPv4 first: an IPv6 link-local address without its scope is the least likely to connect.
            val ordered = addresses.sortedBy { if (it is Inet4Address) 0 else 1 }
            val sighting = SiteSighting(parsed.serviceName, parsed.tlsHost, parsed.port, ordered)
            synchronized(guard) {
                if (stopped) return
                byService[sighting.serviceName] = sighting
                if (firstMatchAt == null && match(sighting)) firstMatchAt = now()
            }
        }

        private fun watch(serviceInfo: NsdServiceInfo) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE) return
            val callback = object : NsdManager.ServiceInfoCallback {
                override fun onServiceInfoCallbackRegistrationFailed(errorCode: Int) {
                    Log.w(TAG, "service info callback failed: $errorCode")
                }
                override fun onServiceUpdated(serviceInfo: NsdServiceInfo) = record(serviceInfo, serviceInfo.hostAddresses)
                override fun onServiceLost() = Unit
                override fun onServiceInfoCallbackUnregistered() = Unit
            }
            synchronized(guard) {
                if (stopped) return
                callbacks += callback
            }
            runCatching { nsd.registerServiceInfoCallback(serviceInfo, executor, callback) }
                .onFailure { Log.w(TAG, "registerServiceInfoCallback failed", it) }
        }

        private fun enqueue(serviceInfo: NsdServiceInfo) {
            synchronized(guard) {
                if (stopped) return
                pending.addLast(serviceInfo)
            }
            resolveNext()
        }

        /** Pre-34 NSD: one resolve in flight at a time. */
        @Suppress("DEPRECATION")
        private fun resolveNext() {
            val next = synchronized(guard) {
                if (stopped || resolving) return
                pending.removeFirstOrNull()?.also { resolving = true } ?: return
            }
            val listener = object : NsdManager.ResolveListener {
                override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) = done()
                override fun onServiceResolved(info: NsdServiceInfo) {
                    record(info, listOfNotNull(info.host))
                    done()
                }
                private fun done() {
                    synchronized(guard) { resolving = false }
                    resolveNext()
                }
            }
            runCatching { nsd.resolveService(next, listener) }.onFailure {
                synchronized(guard) { resolving = false }
            }
        }
    }

    private companion object {
        const val TAG = "NsdSiteBrowser"
        const val POLL_MS = 50L

        /** After the first match, how long to keep listening for a second address of the same name (conflict). */
        const val SETTLE_MS = 400L

        fun now(): Long = System.nanoTime() / 1_000_000
    }
}
