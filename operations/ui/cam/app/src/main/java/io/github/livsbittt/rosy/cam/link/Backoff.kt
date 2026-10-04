package io.github.livsbittt.rosy.cam.link

/** Reconnect delays 1 s -> 2 s -> 5 s (cap), reset after a successful connection (design section 5). */
class Backoff(
    private val stepsMs: List<Long> = listOf(1_000L, 2_000L, 5_000L),
    private val random: () -> Double = { kotlin.random.Random.nextDouble() },
) {
    private var attempt = 0

    @Synchronized
    fun nextDelayMs(): Long {
        val delay = stepsMs[attempt.coerceAtMost(stepsMs.lastIndex)]
        if (attempt < stepsMs.size) attempt++
        return (delay * (0.8 + 0.2 * random().coerceIn(0.0, 1.0))).toLong()
    }

    @Synchronized
    fun reset() {
        attempt = 0
    }
}
