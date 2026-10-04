package io.github.livsbittt.rosy.pilot

/** Shared by adapter instances: a new binding cannot overtake a retiring Binder. */
class DiscoveryRetirementFence {
    private val retiring = mutableSetOf<Any>()
    private val waiters = mutableMapOf<Any, () -> Unit>()
    fun hold(owner: Any, alive: Boolean = true) { retiring.add(owner); if (!alive) died(owner) }
    fun await(owner: Any, bind: () -> Unit) { if (retiring.isEmpty()) bind() else waiters[owner] = bind }
    fun cancel(owner: Any) { waiters.remove(owner) }
    fun died(owner: Any) {
        retiring.remove(owner)
        if (retiring.isEmpty()) { val ready = waiters.values.toList(); waiters.clear(); ready.forEach { it() } }
    }
}

/** Resolver epochs change independently of verified robot presence and its original TTL. */
class DiscoveryPresenceLedger(private val store: CandidateStore, private val now: () -> Long) {
    private data class Presence(val epoch: Long, val child: Long, var local: Long, var stamp: Long)
    private val present = mutableMapOf<String, Presence>()
    private var epoch = 0L
    fun newEpoch() { epoch++ }
    fun found(name: String, child: Long) {
        val prior = present[name]
        store.found(name)?.let { present[name] = Presence(epoch, child, it, prior?.stamp ?: -1) }
    }
    fun generation(name: String, child: Long): Long? = present[name]?.takeIf { it.epoch == epoch && it.child == child }?.local
    fun resolved(name: String, child: Long, sentAt: Long) {
        present[name]?.takeIf { it.epoch == epoch && it.child == child }?.stamp = sentAt
    }
    fun lost(name: String, child: Long): Boolean {
        if (generation(name, child) == null) return false
        present.remove(name); store.lost(name); return true
    }
    fun expire(): Boolean {
        var changed = false
        present.forEach { (name, row) ->
            if (row.stamp >= 0 && now() - row.stamp >= 60000) {
                store.lost(name); store.found(name)?.let { row.local = it }; row.stamp = -1; changed = true
            }
        }
        return changed
    }
    fun clearTracking() { present.clear() }
}

/** Monotonic clock supplied by the adapter; retirement requires confirmed Binder death. */
class DiscoverySupervisor(private val now: () -> Long) {
    enum class Action { NONE, RETIRE, BIND }
    var epoch = 0L; private set
    var status = "같은 Wi-Fi에서 로봇을 찾고 있습니다…"; private set
    private var running = false
    private var retiring: Long? = null
    private var deadline: Long? = null
    private val queries = mutableMapOf<Long, Long>()
    private var retryAt: Long? = null
    private val restarts = ArrayDeque<Long>()
    fun start(): Long {
        running = true; retiring = null; deadline = now() + 12000; queries.clear(); retryAt = null
        status = "같은 Wi-Fi에서 로봇을 찾고 있습니다…"
        return ++epoch
    }
    fun connected(token: Long) {
        if (accepts(token)) { deadline = null; status = "같은 Wi-Fi에서 로봇을 찾고 있습니다…" }
    }
    fun queryStarted(token: Long, id: Long) { if (accepts(token)) queries.putIfAbsent(id, now() + 12000) }
    fun queryEnded(token: Long, id: Long) { if (accepts(token)) queries.remove(id) }
    fun accepts(token: Long) = running && retiring == null && retryAt == null && token == epoch
    fun acceptsEvent(token: Long, sentAt: Long) = accepts(token) && sentAt <= now() && now() - sentAt < 60000
    fun failed(token: Long): Action {
        if (!accepts(token)) return Action.NONE
        retiring = token; epoch++; deadline = now() + 12000; queries.clear()
        status = "로봇 검색 연결을 복구하고 있습니다…"
        return Action.RETIRE
    }
    fun died(token: Long) {
        if (!running) return
        if (retiring == null && accepts(token)) failed(token)
        if (retiring != token) return
        retiring = null; deadline = null
        while (restarts.isNotEmpty() && now() - restarts.first() >= 300000) restarts.removeFirst()
        if (restarts.size >= 3) { exhaust(); return }
        retryAt = now() + (1000L shl restarts.size)
        restarts.addLast(now())
    }
    fun poll(): Action {
        if (!running) return Action.NONE
        if (retiring != null && deadline?.let { now() >= it } == true) { exhaust(); return Action.NONE }
        if (deadline?.let { now() >= it } == true || queries.values.any { now() >= it }) return failed(epoch)
        if (retryAt?.let { now() >= it } == true) { retryAt = null; deadline = now() + 12000; return Action.BIND }
        return Action.NONE
    }
    private fun exhaust() {
        running = false; deadline = null; retryAt = null
        status = "검색 연결을 복구하지 못했습니다. ‘다시 찾기’를 눌러주세요."
    }
    fun stop() { running = false; epoch++; retiring = null; deadline = null; retryAt = null; queries.clear() }
}
