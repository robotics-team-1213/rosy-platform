package io.github.livsbittt.rosy.pilot

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import java.util.concurrent.Executor

/** OS adapter only: profile scope and authenticated TLS own approval. */
class RobotDiscovery(context: Context, private val store: CandidateStore, private val changed: () -> Unit) {
    private val manager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val main = Handler(Looper.getMainLooper())
    private val pending = ArrayDeque<Pair<NsdServiceInfo, Long>>()
    private val watches = mutableMapOf<String, NsdManager.ServiceInfoCallback>()
    private val services = mutableMapOf<String, Pair<NsdServiceInfo, Long>>()
    private var stopped = true
    private var active = false
    private var resolveVersion = 0
    private var lock: WifiManager.MulticastLock? = null
    private fun trace(message: String) = android.util.Log.i("RosyPilotDiscovery", message)
    private val listener = object : NsdManager.DiscoveryListener {
        override fun onDiscoveryStarted(type: String) { trace("Discovery started type=$type") }
        override fun onDiscoveryStopped(type: String) { trace("Discovery stopped type=$type") }
        override fun onStartDiscoveryFailed(type: String, error: Int) { trace("Discovery failed type=$type error=$error"); changed() }
        override fun onStopDiscoveryFailed(type: String, error: Int) = Unit
        override fun onServiceFound(info: NsdServiceInfo) { main.post {
            trace("Found name=${info.serviceName} type=${info.serviceType} stopped=$stopped")
            if (stopped || info.serviceType.trimEnd('.') != "_rosy._tcp") return@post
            val generation = store.found(info.serviceName) ?: return@post
            services[info.serviceName] = info to generation
            if (Build.VERSION.SDK_INT >= 34) watch(info, generation)
            else if (pending.none { it.first.serviceName == info.serviceName }) { pending.add(info to generation); next() }
        } }
        override fun onServiceLost(info: NsdServiceInfo) { main.post {
            trace("Lost name=${info.serviceName} stopped=$stopped")
            if (stopped) return@post
            store.lost(info.serviceName)
            services.remove(info.serviceName)
            pending.removeAll { it.first.serviceName == info.serviceName }
            if (Build.VERSION.SDK_INT >= 34) watches.remove(info.serviceName)?.let { runCatching { manager.unregisterServiceInfoCallback(it) } }
            changed()
        } }
    }
    fun start() {
        stopped = false
        lock = wifi.createMulticastLock("rosy-pilot-discovery").apply { setReferenceCounted(false); acquire() }
        manager.discoverServices("_rosy._tcp.", NsdManager.PROTOCOL_DNS_SD, listener)
        main.postDelayed(object : Runnable {
            override fun run() {
                if (stopped) return
                if (Build.VERSION.SDK_INT < 34) {
                    services.values.forEach { entry -> if (pending.none { it.first.serviceName == entry.first.serviceName }) pending.add(entry) }
                    next()
                } else {
                    services.values.toList().filter { !store.fresh(it.first.serviceName) }.forEach { entry ->
                        watches.remove(entry.first.serviceName)?.let { runCatching { manager.unregisterServiceInfoCallback(it) } }
                        watch(entry.first, entry.second)
                    }
                }
                main.postDelayed(this, 20000 + kotlin.random.Random.nextLong(5000))
            }
        }, 20000)
    }
    fun stop(clearCandidates: Boolean = true) {
        stopped = true; resolveVersion++; active = false
        main.removeCallbacksAndMessages(null); pending.clear()
        runCatching { manager.stopServiceDiscovery(listener) }
        if (Build.VERSION.SDK_INT >= 34) watches.values.forEach { runCatching { manager.unregisterServiceInfoCallback(it) } }
        watches.clear(); services.clear(); if (clearCandidates) store.clear()
        lock?.let { if (it.isHeld) it.release() }; lock = null
    }
    private fun record(info: NsdServiceInfo, generation: Long, addresses: List<String>) {
        if (stopped) return
        fun rejected(reason: String) { trace("Rejected name=${info.serviceName} port=${info.port} addresses=${addresses.joinToString(",")} reason=$reason") }
        fun txt(key: String) = info.attributes[key]?.toString(Charsets.UTF_8)?.trim()?.lowercase()
        if (txt("network") == "ap") { rejected("ap_mode"); return }
        val secure = txt("tls") == "required"
        // InetAddress.hostName can run reverse DNS and crash the Android main thread.
        @Suppress("DEPRECATION") val cached = info.host?.toString()?.substringBefore('/')?.lowercase()?.trimEnd('.')
        @Suppress("DEPRECATION") val host = txt("tls_host") ?: cached?.takeIf { io.github.livsbittt.rosy.cam.settings.SiteLink.isTlsHost(it) }
            ?: info.host?.hostAddress?.takeUnless { secure } ?: run { rejected("secure_host_missing"); return }
        val isName = io.github.livsbittt.rosy.cam.settings.SiteLink.isTlsHost(host)
        if (!isName && (secure || !io.github.livsbittt.rosy.cam.settings.SiteLink.isIpLiteral(host))) { rejected("bad_host"); return }
        val ips = addresses.filter { address ->
            val reason = io.github.livsbittt.rosy.cam.settings.RobotCoreServiceRecord.rejection(
                info.serviceType, address, info.port, info.attributes, host.takeIf { isName })
            if (reason != null) rejected(reason)
            reason == null
        }
        if (ips.isEmpty() || info.port !in 1..65535) { rejected("no_eligible_address"); return }
        store.resolved(info.serviceName, generation, Candidate(host, info.port, ips.sorted(), txt("name") ?: info.serviceName, txt("robot_id").orEmpty(), secure))
        android.util.Log.i("RosyPilotDiscovery", "Resolved ${info.serviceName} host=$host port=${info.port} addresses=${ips.sorted().joinToString(",")} tls=$secure")
        changed()
    }
    private fun watch(info: NsdServiceInfo, generation: Long) {
        if (Build.VERSION.SDK_INT < 34 || info.serviceName in watches) return
        val callback = object : NsdManager.ServiceInfoCallback {
            override fun onServiceInfoCallbackRegistrationFailed(error: Int) { changed() }
            override fun onServiceInfoCallbackUnregistered() = Unit
            override fun onServiceLost() { if (!stopped && watches[info.serviceName] === this) {
                store.lost(info.serviceName); services.remove(info.serviceName)
                watches.remove(info.serviceName)?.let { runCatching { manager.unregisterServiceInfoCallback(it) } }
                changed()
            } }
            override fun onServiceUpdated(update: NsdServiceInfo) {
                if (stopped || watches[info.serviceName] !== this || services[info.serviceName]?.second != generation) return
                record(update, generation, update.hostAddresses.mapNotNull { it.hostAddress })
            }
        }
        watches[info.serviceName] = callback
        runCatching { manager.registerServiceInfoCallback(info, Executor { main.post(it) }, callback) }
    }
    @Suppress("DEPRECATION") private fun next() {
        if (stopped || active) return
        val entry = pending.removeFirstOrNull() ?: return
        active = true
        val version = ++resolveVersion
        val started = android.os.SystemClock.elapsedRealtime()
        trace("Resolve start name=${entry.first.serviceName} version=$version")
        fun done() { if (!stopped && version == resolveVersion) { active = false; next() } }
        val resolver = object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, error: Int) { main.post {
                trace("Resolve failed name=${info.serviceName} version=$version error=$error elapsedMs=${android.os.SystemClock.elapsedRealtime() - started}")
                done()
            } }
            override fun onServiceResolved(info: NsdServiceInfo) { main.post {
                trace("Resolve callback name=${info.serviceName} version=$version current=$resolveVersion stopped=$stopped elapsedMs=${android.os.SystemClock.elapsedRealtime() - started}")
                if (!stopped && version == resolveVersion) {
                    record(info, entry.second, listOfNotNull(info.host?.hostAddress)); done()
                }
            } }
        }
        runCatching { manager.resolveService(entry.first, resolver) }.onFailure { done() }
        main.postDelayed({ if (!stopped && version == resolveVersion && active) trace("Resolve local timeout name=${entry.first.serviceName} version=$version elapsedMs=${android.os.SystemClock.elapsedRealtime() - started}"); done() }, 2000)
    }
}
