package io.github.livsbittt.rosy.cam.settings

/** Per-session limit applies to all sightings, including invalid and repeatedly rediscovered names. */
class DiscoveryBudget(private val limit: Int = 64) {
    private val seen = mutableSetOf<String>()
    private val present = mutableMapOf<String, Int>()
    private var generation = 0
    private var stopped = false
    fun claim(key: String): Boolean {
        if (stopped || key in present || generation >= limit * 4 || (key !in seen && seen.size >= limit)) return false
        seen.add(key)
        present[key] = ++generation
        return true
    }
    fun generation(key: String): Int? = present[key]
    fun current(key: String, version: Int?): Boolean = !stopped && version != null && present[key] == version
    fun lost(key: String) { present.remove(key) }
    fun stop() { stopped = true; present.clear() }
}
