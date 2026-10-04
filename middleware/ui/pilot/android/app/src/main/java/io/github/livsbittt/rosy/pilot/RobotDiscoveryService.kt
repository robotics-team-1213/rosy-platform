package io.github.livsbittt.rosy.pilot

import android.app.Service
import android.content.Intent
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import android.os.*
import java.util.concurrent.Executor

/** Private, bound-only process: its Binder death releases Android 12's native resolve slot. */
class RobotDiscoveryService : Service() {
    companion object {
        const val START = 1; const val STOP = 2; const val FOUND = 3; const val LOST = 4
        const val RESOLVED = 5; const val QUERY_START = 6; const val QUERY_END = 7; const val FAILED = 8
        const val STARTED = 9
    }
    private val main = Handler(Looper.getMainLooper())
    private lateinit var manager: NsdManager
    private var client: Messenger? = null
    private var epoch = 0L
    private var stopped = true
    private var started = false
    private var lock: WifiManager.MulticastLock? = null
    private val seen = mutableSetOf<String>()
    private val services = mutableMapOf<String, Pair<NsdServiceInfo, Long>>()
    private val watches = mutableMapOf<String, NsdManager.ServiceInfoCallback>()
    private val watchQueries = mutableMapOf<String, Long>()
    private val pending = ArrayDeque<Pair<NsdServiceInfo, Long>>()
    private var presence = 0L
    private var query = 0L
    private var discoveryQuery = 0L
    private var active = false
    private var shuttingDown = false
    private val messenger = Messenger(object : Handler(Looper.getMainLooper()) {
        override fun handleMessage(msg: Message) {
            // exported=false prevents external binding; Messenger retains sender UID across IPC.
            if (msg.sendingUid != applicationInfo.uid) return
            when (msg.what) {
                START -> if (stopped) { epoch = msg.data.getLong("epoch"); client = msg.replyTo; start() }
                STOP -> if (msg.data.getLong("epoch") == epoch) shutdown()
            }
        }
    })
    override fun onCreate() { super.onCreate(); manager = getSystemService(NSD_SERVICE) as NsdManager }
    override fun onBind(intent: Intent): IBinder = messenger.binder
    override fun onUnbind(intent: Intent): Boolean { shutdown(); return false }
    override fun onDestroy() { shutdown(); super.onDestroy() }
    private fun emit(kind: Int, info: NsdServiceInfo? = null, generation: Long = 0, id: Long = 0) {
        if (stopped) return
        val data = Bundle().apply {
            putLong("epoch", epoch); putLong("sentAt", SystemClock.elapsedRealtime())
            putLong("generation", generation); putLong("query", id)
            if (info != null) putParcelable("info", info)
        }
        runCatching { client?.send(Message.obtain(null, kind).apply { this.data = data }) }.onFailure { shutdown() }
    }
    private val listener = object : NsdManager.DiscoveryListener {
        override fun onDiscoveryStarted(type: String) { main.post { emit(QUERY_END, id = discoveryQuery) } }
        override fun onDiscoveryStopped(type: String) = Unit
        override fun onStartDiscoveryFailed(type: String, error: Int) { main.post { emit(FAILED) } }
        override fun onStopDiscoveryFailed(type: String, error: Int) = Unit
        override fun onServiceFound(info: NsdServiceInfo) { main.post {
            if (stopped || info.serviceType.trimEnd('.') != "_rosy._tcp") return@post
            if (info.serviceName !in seen && seen.size >= 64) return@post
            seen.add(info.serviceName)
            val generation = services[info.serviceName]?.second ?: ++presence
            services[info.serviceName] = info to generation
            emit(FOUND, info, generation)
            if (Build.VERSION.SDK_INT >= 34) watch(info, generation)
            else { enqueue(info to generation); next() }
        } }
        override fun onServiceLost(info: NsdServiceInfo) { main.post {
            if (stopped) return@post
            val generation = services.remove(info.serviceName)?.second ?: return@post
            pending.removeAll { it.first.serviceName == info.serviceName }
            if (Build.VERSION.SDK_INT >= 34) watches.remove(info.serviceName)?.let { runCatching { manager.unregisterServiceInfoCallback(it) } }
            watchQueries.remove(info.serviceName)?.let { emit(QUERY_END, id = it) }
            emit(LOST, info, generation)
        } }
    }
    private fun enqueue(entry: Pair<NsdServiceInfo, Long>) {
        if (pending.none { it.first.serviceName == entry.first.serviceName }) pending.add(entry)
    }
    private fun start() {
        stopped = false
        runCatching {
            lock = (applicationContext.getSystemService(WIFI_SERVICE) as WifiManager)
                .createMulticastLock("rosy-pilot-discovery").apply { setReferenceCounted(false); acquire() }
            discoveryQuery = ++query
            emit(QUERY_START, id = discoveryQuery)
            manager.discoverServices("_rosy._tcp.", NsdManager.PROTOCOL_DNS_SD, listener)
            started = true
            emit(STARTED)
        }.onFailure { emit(FAILED) }
        main.postDelayed(object : Runnable {
            override fun run() {
                if (stopped) return
                if (Build.VERSION.SDK_INT < 34) { services.values.forEach { enqueue(it) }; next() }
                else services.values.toList().forEach { entry ->
                    watches.remove(entry.first.serviceName)?.let { runCatching { manager.unregisterServiceInfoCallback(it) } }
                    watchQueries.remove(entry.first.serviceName)?.let { emit(QUERY_END, id = it) }
                    watch(entry.first, entry.second)
                }
                main.postDelayed(this, 20000 + kotlin.random.Random.nextLong(5000))
            }
        }, 20000)
    }
    @Suppress("DEPRECATION") private fun next() {
        if (stopped || active) return
        val entry = pending.removeFirstOrNull() ?: return
        if (services[entry.first.serviceName]?.second != entry.second) { next(); return }
        active = true
        val id = ++query
        emit(QUERY_START, id = id)
        fun done() { if (!stopped && id == query) { active = false; emit(QUERY_END, id = id); next() } }
        val resolver = object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, error: Int) { main.post {
                android.util.Log.i("RosyPilotDiscovery", "Resolve failed error=$error query=$id")
                if (error == NsdManager.FAILURE_ALREADY_ACTIVE) emit(FAILED) else done()
            } }
            override fun onServiceResolved(info: NsdServiceInfo) { main.post {
                if (!stopped && id == query && services[entry.first.serviceName]?.second == entry.second)
                    emit(RESOLVED, info, entry.second)
                done()
            } }
        }
        runCatching { manager.resolveService(entry.first, resolver) }.onFailure { emit(FAILED) }
        // Android 12 cannot cancel a resolve publicly. The parent supervises its real lifetime.
    }
    private fun watch(info: NsdServiceInfo, generation: Long) {
        if (Build.VERSION.SDK_INT < 34 || info.serviceName in watches) return
        val id = ++query
        watchQueries[info.serviceName] = id
        emit(QUERY_START, id = id)
        val callback = object : NsdManager.ServiceInfoCallback {
            override fun onServiceInfoCallbackRegistrationFailed(error: Int) { if (!stopped && watches[info.serviceName] === this) emit(FAILED) }
            override fun onServiceInfoCallbackUnregistered() = Unit
            override fun onServiceLost() {
                if (stopped || watches[info.serviceName] !== this) return
                services.remove(info.serviceName); watches.remove(info.serviceName)
                watchQueries.remove(info.serviceName)
                runCatching { manager.unregisterServiceInfoCallback(this) }
                emit(QUERY_END, id = id)
                emit(LOST, info, generation)
            }
            override fun onServiceUpdated(update: NsdServiceInfo) {
                if (!stopped && watches[info.serviceName] === this && services[info.serviceName]?.second == generation) {
                    emit(RESOLVED, update, generation)
                    emit(QUERY_END, id = id)
                }
            }
        }
        watches[info.serviceName] = callback
        runCatching { manager.registerServiceInfoCallback(info, Executor { main.post(it) }, callback) }.onFailure { emit(FAILED) }
    }
    private fun shutdown() {
        if (shuttingDown) return
        shuttingDown = true
        stopped = true; main.removeCallbacksAndMessages(null)
        if (started) runCatching { manager.stopServiceDiscovery(listener) }
        if (Build.VERSION.SDK_INT >= 34) watches.values.forEach { runCatching { manager.unregisterServiceInfoCallback(it) } }
        watches.clear(); watchQueries.clear(); services.clear(); pending.clear(); client = null
        lock?.let { if (it.isHeld) it.release() }; lock = null
        android.util.Log.i("RosyPilotDiscovery", "Dedicated discovery process stopping pid=${Process.myPid()}")
        // Only this manifest-declared dedicated process; never the activity or another application.
        Process.killProcess(Process.myPid())
    }
}
