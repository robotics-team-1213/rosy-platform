package io.github.livsbittt.rosy.overhead.camera

/**
 * Keeps JPEGs under the adapter's `max_bytes` on detailed scenes: an oversize frame is
 * re-encoded at most [MAX_RETRIES] times, [STEP] lower each time and never below [FLOOR].
 * The next frame starts at the last quality that fit and climbs back by [RECOVER_STEP] after
 * [RECOVER_AFTER] frames in a row fit. The configured `jpeg_quality` stays a ceiling.
 * Analysis-thread only; not thread-safe.
 */
class AdaptiveJpegQuality {
    private var effective: Int? = null
    private var current = 0
    private var retries = 0
    private var fitRun = 0

    /** Quality for the first encode of a frame, given the configured `jpeg_quality`. */
    fun start(configured: Int): Int {
        val base = effective?.coerceAtMost(configured) ?: configured
        current = base
        retries = 0
        return current
    }

    /** Quality for one more encode of the same frame, or null to drop it. */
    fun retryAfterOversize(): Int? {
        fitRun = 0
        if (retries >= MAX_RETRIES || current <= FLOOR) return null
        retries++
        current = (current - STEP).coerceAtLeast(FLOOR)
        effective = current
        return current
    }

    /** The last encode fit under `max_bytes`. */
    fun encoded() {
        effective = current
        fitRun++
        if (fitRun >= RECOVER_AFTER) {
            effective = current + RECOVER_STEP
            fitRun = 0
        }
    }

    companion object {
        const val STEP = 10
        const val FLOOR = 30
        const val MAX_RETRIES = 2
        const val RECOVER_AFTER = 30
        const val RECOVER_STEP = 5
    }
}
