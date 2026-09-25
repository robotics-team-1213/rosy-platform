package io.github.livsbittt.rosy.overhead.link

/** Reconnect delays 1 s -> 2 s -> 5 s (cap), reset after a successful connection (design section 5). */
class Backoff(private val stepsMs: List<Long> = listOf(1_000L, 2_000L, 5_000L)) {
    private var attempt = 0

    @Synchronized
    fun nextDelayMs(): Long {
        val delay = stepsMs[attempt.coerceAtMost(stepsMs.lastIndex)]
        if (attempt < stepsMs.size) attempt++
        return delay
    }

    @Synchronized
    fun reset() {
        attempt = 0
    }
}
