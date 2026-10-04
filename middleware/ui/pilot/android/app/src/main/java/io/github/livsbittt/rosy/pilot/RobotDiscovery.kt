package io.github.livsbittt.rosy.pilot

import android.content.*
import android.net.nsd.NsdServiceInfo
import android.os.*

/** Main-process policy adapter; only its private child owns the native NSD client. */
class RobotDiscovery(context: Context, private val store: CandidateStore, private val changed: () -> Unit) {
    companion object { private val retirement = DiscoveryRetirementFence() }
    private val context = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val supervisor = DiscoverySupervisor { SystemClock.elapsedRealtime() }
    private var stopped = true
    private var binding: Binding? = null
    private val presences = DiscoveryPresenceLedger(store) { SystemClock.elapsedRealtime() }
    val status: String get() = supervisor.status
    private fun trace(message: String) = android.util.Log.i("RosyPilotDiscovery", message)
    private inner class Binding(val token: Long) : ServiceConnection {
        var bound = false
        var retiring = false
        var remote: Messenger? = null
        var binder: IBinder? = null
        val death = IBinder.DeathRecipient { main.post { died(this) } }
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
            binder = service
            runCatching {
                service.linkToDeath(death, 0)
                remote = Messenger(service)
                if (stopped || retiring || binding !== this || !supervisor.accepts(token)) { release(this); return }
                send(RobotDiscoveryService.START, token, remote)
                trace("Discovery child connected epoch=$token")
            }.onFailure { recover(token); if (!service.isBinderAlive) died(this) }
        }
        override fun onServiceDisconnected(name: ComponentName) { died(this) }
        override fun onBindingDied(name: ComponentName) { died(this) }
        override fun onNullBinding(name: ComponentName) { recover(token); died(this) }
    }
    private val replies = Messenger(object : Handler(Looper.getMainLooper()) {
        @Suppress("DEPRECATION") override fun handleMessage(msg: Message) {
            if (stopped || msg.sendingUid != context.applicationInfo.uid) return
            val data = msg.data
            val token = data.getLong("epoch")
            val sentAt = data.getLong("sentAt")
            if (!supervisor.acceptsEvent(token, sentAt)) return
            when (msg.what) {
                RobotDiscoveryService.STARTED -> { supervisor.connected(token); changed() }
                RobotDiscoveryService.QUERY_START -> supervisor.queryStarted(token, data.getLong("query"))
                RobotDiscoveryService.QUERY_END -> supervisor.queryEnded(token, data.getLong("query"))
                RobotDiscoveryService.FAILED -> recover(token)
                else -> {
                    val info = data.getParcelable<NsdServiceInfo>("info") ?: return
                    val name = info.serviceName
                    val generation = data.getLong("generation")
                    when (msg.what) {
                        RobotDiscoveryService.FOUND -> {
                            presences.found(name, generation)
                        }
                        RobotDiscoveryService.LOST -> if (presences.lost(name, generation)) changed()
                        RobotDiscoveryService.RESOLVED -> {
                            val local = presences.generation(name, generation) ?: return
                            val addresses = if (Build.VERSION.SDK_INT >= 34) info.hostAddresses.mapNotNull { it.hostAddress }
                                else listOfNotNull(info.host?.hostAddress)
                            if (!record(info, local, addresses)) return
                            presences.resolved(name, generation, sentAt)
                        }
                    }
                }
            }
        }
    })
    private val tick = object : Runnable {
        override fun run() {
            if (stopped) return
            val prior = supervisor.status
            when (supervisor.poll()) {
                DiscoverySupervisor.Action.RETIRE -> retire()
                DiscoverySupervisor.Action.BIND -> bind(supervisor.epoch)
                else -> Unit
            }
            if (presences.expire() || prior != supervisor.status) changed()
            main.postDelayed(this, 250)
        }
    }
    fun start() {
        if (!stopped) return
        stopped = false; bind(supervisor.start()); main.postDelayed(tick, 250)
    }
    fun stop(clearCandidates: Boolean = true) {
        stopped = true; supervisor.stop(); main.removeCallbacks(tick)
        retirement.cancel(this)
        val old = binding; binding = null
        old?.let { release(it) }
        presences.clearTracking(); if (clearCandidates) store.clear()
    }
    private fun bind(token: Long) {
        if (stopped || !supervisor.accepts(token)) return
        retirement.await(this) { if (!stopped && supervisor.accepts(token)) bindReady(token) }
    }
    private fun bindReady(token: Long) {
        val next = Binding(token); binding = next
        next.bound = runCatching { context.bindService(Intent(context, RobotDiscoveryService::class.java), next, Context.BIND_AUTO_CREATE) }.getOrDefault(false)
        if (!next.bound) { recover(token); died(next) }
    }
    private fun send(kind: Int, token: Long, remote: Messenger?) {
        runCatching { remote?.send(Message.obtain(null, kind).apply { data = Bundle().apply { putLong("epoch", token) }; replyTo = replies }) }
    }
    private fun recover(token: Long) { if (supervisor.failed(token) == DiscoverySupervisor.Action.RETIRE) retire() }
    private fun retire() {
        retirement.cancel(this)
        val old = binding; binding = null
        // Verified rows retain their original bounded TTL; resolver failure is not robot loss.
        presences.newEpoch()
        old?.let { release(it) }
        trace("Discovery recovery awaiting child Binder death epoch=${old?.token}"); changed()
    }
    private fun unbind(old: Binding) {
        if (old.bound) { old.bound = false; runCatching { context.unbindService(old) } }
    }
    private fun release(old: Binding) {
        old.retiring = true; retirement.hold(old, old.binder?.isBinderAlive != false)
        if (old.binder?.isBinderAlive == false) { died(old); return }
        // Keep a not-yet-connected binding until we can observe the child's Binder death.
        if (old.binder != null) { send(RobotDiscoveryService.STOP, old.token, old.remote); unbind(old) }
    }
    private fun died(old: Binding) {
        if (old.binder?.isBinderAlive == true) { recover(old.token); return }
        runCatching { old.binder?.unlinkToDeath(old.death, 0) }
        if (binding === old) { recover(old.token) }
        unbind(old); supervisor.died(old.token)
        retirement.died(old)
        trace("Discovery child Binder death epoch=${old.token}"); changed()
    }
    private fun record(info: NsdServiceInfo, generation: Long, addresses: List<String>): Boolean {
        if (stopped) return false
        fun rejected(reason: String) { trace("Rejected name=${info.serviceName} port=${info.port} addresses=${addresses.joinToString(",")} reason=$reason") }
        fun txt(key: String) = info.attributes[key]?.toString(Charsets.UTF_8)?.trim()?.lowercase()
        if (txt("network") == "ap") { rejected("ap_mode"); return false }
        val secure = txt("tls") == "required"
        // InetAddress.hostName can run reverse DNS and crash the Android main thread.
        @Suppress("DEPRECATION") val cached = info.host?.toString()?.substringBefore('/')?.lowercase()?.trimEnd('.')
        @Suppress("DEPRECATION") val host = txt("tls_host") ?: cached?.takeIf { io.github.livsbittt.rosy.cam.settings.SiteLink.isTlsHost(it) }
            ?: info.host?.hostAddress?.takeUnless { secure } ?: run { rejected("secure_host_missing"); return false }
        val isName = io.github.livsbittt.rosy.cam.settings.SiteLink.isTlsHost(host)
        if (!isName && (secure || !io.github.livsbittt.rosy.cam.settings.SiteLink.isIpLiteral(host))) { rejected("bad_host"); return false }
        val ips = addresses.filter { address ->
            val reason = io.github.livsbittt.rosy.cam.settings.RobotCoreServiceRecord.rejection(
                info.serviceType, address, info.port, info.attributes, host.takeIf { isName })
            if (reason != null) rejected(reason)
            reason == null
        }
        if (ips.isEmpty() || info.port !in 1..65535) { rejected("no_eligible_address"); return false }
        store.resolved(info.serviceName, generation, Candidate(host, info.port, ips.sorted(), txt("name") ?: info.serviceName, txt("robot_id").orEmpty(), secure))
        android.util.Log.i("RosyPilotDiscovery", "Resolved ${info.serviceName} host=$host port=${info.port} addresses=${ips.sorted().joinToString(",")} tls=$secure")
        changed()
        return true
    }
}
