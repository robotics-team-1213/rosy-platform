package io.github.livsbittt.rosy.cam.settings

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import java.net.InetAddress
import java.util.concurrent.Executor

/** Shared initial/reconnect NSD lifecycle. All mutable state and callbacks run on the main looper. */
internal class NsdDiscoverySession(
    context: Context,
    private val types: List<String>,
    private val onRecord: (NsdServiceInfo, List<InetAddress>) -> Unit,
    private val onLost: (String, String) -> Unit,
    private val onFinished: () -> Unit = {},
) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val main = Handler(Looper.getMainLooper())
    private val executor = Executor { task -> main.post(task) }
    /** Late NSD callbacks after stop must not crash (origin fix c025660ef "tolerate late NSD callbacks"); the main looper never rejects, the wrapper keeps that true by contract. */
    private val callbackExecutor = NsdCallbackExecutor(executor)
    private val budget = DiscoveryBudget()
    private val listeners = mutableListOf<NsdManager.DiscoveryListener>()
    private val callbacks = mutableMapOf<String, NsdManager.ServiceInfoCallback>()
    private val pending = ArrayDeque<NsdServiceInfo>()
    private var lock: WifiManager.MulticastLock? = null
    @Volatile private var stopped = false
    private var started = false
    private var resolving = false
    private var resolveGeneration = 0
    private val retried = mutableSetOf<String>()

    fun start(timeoutMs: Long) = dispatch {
        if (stopped || started) return@dispatch
        started = true
        lock = runCatching { wifi.createMulticastLock("rosy-discovery").apply { setReferenceCounted(false); acquire() } }.getOrNull()
        types.forEach { type ->
            val listener = object : NsdManager.DiscoveryListener {
                override fun onDiscoveryStarted(serviceType: String) = Unit
                override fun onDiscoveryStopped(serviceType: String) = Unit
                override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
                override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
                override fun onServiceFound(info: NsdServiceInfo) = dispatch {
                    if (stopped || normalizeServiceType(info.serviceType) != normalizeServiceType(type) ||
                        !budget.claim("${normalizeServiceType(type)}|${info.serviceName}")) return@dispatch
                    if (Build.VERSION.SDK_INT >= 34) watch(info) else { pending.addLast(info); resolveNext() }
                }
                override fun onServiceLost(info: NsdServiceInfo) = dispatch {
                    if (!stopped) withdraw(info)
                }
            }
            listeners += listener
            runCatching { nsd.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, listener) }
        }
        main.postDelayed({ finish() }, timeoutMs.coerceIn(1, 18_000))
    }

    /** Cancellation never emits callbacks, including a delayed completion or an outstanding legacy resolve. */
    fun stop() {
        stopped = true
        dispatch { cleanup() }
    }

    private fun finish() {
        if (stopped) return
        stopped = true
        cleanup()
        onFinished()
    }

    private fun cleanup() {
        budget.stop()
        main.removeCallbacksAndMessages(null)
        pending.clear()
        resolveGeneration++
        listeners.forEach { runCatching { nsd.stopServiceDiscovery(it) } }
        listeners.clear()
        if (Build.VERSION.SDK_INT >= 34) callbacks.values.forEach { runCatching { nsd.unregisterServiceInfoCallback(it) } }
        callbacks.clear()
        runCatching { lock?.let { if (it.isHeld) it.release() } }
        lock = null
    }

    private fun watch(info: NsdServiceInfo) {
        if (Build.VERSION.SDK_INT < 34 || stopped) return
        val key = key(info)
        val version = budget.generation(key)
        val callback = object : NsdManager.ServiceInfoCallback {
            override fun onServiceInfoCallbackRegistrationFailed(errorCode: Int) = Unit
            override fun onServiceInfoCallbackUnregistered() = Unit
            override fun onServiceLost() { if (budget.current(key, version)) withdraw(info) }
            override fun onServiceUpdated(serviceInfo: NsdServiceInfo) { if (budget.current(key, version)) onRecord(serviceInfo, serviceInfo.hostAddresses) }
        }
        callbacks[key] = callback
        runCatching { nsd.registerServiceInfoCallback(info, callbackExecutor, callback) }
            .onFailure { callbacks.remove(key) }
    }

    @Suppress("DEPRECATION")
    private fun resolveNext() {
        if (stopped || resolving) return
        val next = pending.removeFirstOrNull() ?: return
        val key = key(next)
        val version = budget.generation(key)
        resolving = true
        val generation = ++resolveGeneration
        fun done() {
            if (stopped || generation != resolveGeneration) return
            resolving = false
            resolveNext()
        }
        val listener = object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) = dispatch {
                if (stopped || generation != resolveGeneration) return@dispatch
                if (budget.current(key, version) && errorCode == NsdManager.FAILURE_ALREADY_ACTIVE && retried.add("${next.serviceType}|${next.serviceName}")) {
                    main.postDelayed({
                        if (!stopped && generation == resolveGeneration) { pending.addFirst(next); done() }
                    }, 200)
                } else done()
            }
            override fun onServiceResolved(info: NsdServiceInfo) = dispatch {
                if (!stopped && generation == resolveGeneration) {
                    if (budget.current(key, version)) onRecord(info, listOfNotNull(info.host))
                    done()
                }
            }
        }
        runCatching { nsd.resolveService(next, listener) }.onFailure { done() }
        // A platform resolve without a callback cannot retain the only queue slot indefinitely.
        main.postDelayed({ done() }, 2_000)
    }

    private fun key(info: NsdServiceInfo) = "${normalizeServiceType(info.serviceType)}|${info.serviceName}"

    private fun withdraw(info: NsdServiceInfo) {
        val key = key(info)
        budget.lost(key)
        pending.removeAll { key(it) == key }
        callbacks.remove(key)?.let { if (Build.VERSION.SDK_INT >= 34) runCatching { nsd.unregisterServiceInfoCallback(it) } }
        onLost(normalizeServiceType(info.serviceType), info.serviceName)
    }

    private fun dispatch(action: () -> Unit) { if (Looper.myLooper() == Looper.getMainLooper()) action() else main.post { action() } }
}
