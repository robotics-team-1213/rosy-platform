package io.github.livsbittt.rosy.overhead.camera

/**
 * Keeps JPEGs under the adapter's `max_bytes` on detailed scenes: an oversize frame is
 * re-encoded at most [MAX_RETRIES] times, [STEP] lower each time and never below [FLOOR].
 * The next frame starts at the lowest quality tried so far, so a scene that stays too
 * detailed does not pay for the same retries on every frame. After [RECOVER_AFTER] frames in
 * a row fit, one frame probes [RECOVER_STEP] higher; if that probe is oversize the retry goes
 * straight back to the last quality that fit instead of stepping below it. The configured
 * `jpeg_quality` stays a ceiling. Analysis-thread only; not thread-safe.
 */
class AdaptiveJpegQuality {
    private var effective: Int? = null
    /** Last quality that fit under `max_bytes`, for display; written on the analysis thread. */
    @Volatile
    var lastFit: Int? = null
        private set
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
        val fit = lastFit
        current = if (fit != null && fit < current) fit else (current - STEP).coerceAtLeast(FLOOR)
        effective = current
        return current
    }

    /** The last encode fit under `max_bytes`. */
    fun encoded() {
        lastFit = current
        effective = current
        fitRun++
        if (fitRun >= RECOVER_AFTER) {
            effective = current + RECOVER_STEP
            fitRun = 0
        }
    }

    /** Forget the adaptation, e.g. when the camera is rebound or the adapter changes the config. */
    fun reset() {
        effective = null
        lastFit = null
        fitRun = 0
    }

    companion object {
        const val STEP = 10
        const val FLOOR = 30
        const val MAX_RETRIES = 2
        const val RECOVER_AFTER = 30
        const val RECOVER_STEP = 5
    }
}
