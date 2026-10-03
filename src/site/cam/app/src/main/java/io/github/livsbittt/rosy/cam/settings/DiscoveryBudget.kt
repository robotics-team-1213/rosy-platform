package io.github.livsbittt.rosy.cam.settings

/** Per-session limit applies to all sightings, including invalid and repeatedly rediscovered names. */
class DiscoveryBudget(private val limit: Int = 64) {
    private val seen = mutableSetOf<String>()
    private var stopped = false
    fun claim(key: String): Boolean = !stopped && key !in seen && seen.size < limit && seen.add(key)
    fun stop() { stopped = true }
}
