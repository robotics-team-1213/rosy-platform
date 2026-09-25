package io.github.livsbittt.rosy.overhead.camera

/**
 * Maps a camera sensor timestamp onto the System.nanoTime clock so age_ms includes the
 * capture-to-analyzer delay. The sensor timebase is either elapsedRealtime or monotonic
 * depending on the device, so both are tried; anything implausible falls back to arrival time.
 */
object CaptureClock {
    private const val MAX_PLAUSIBLE_AGE_NANOS = 2_000_000_000L

    fun toMonotonic(sensorNanos: Long, nowMonoNanos: Long, nowRealtimeNanos: Long): Long {
        val realtimeAge = nowRealtimeNanos - sensorNanos
        if (realtimeAge in 0..MAX_PLAUSIBLE_AGE_NANOS) return nowMonoNanos - realtimeAge
        val monoAge = nowMonoNanos - sensorNanos
        if (monoAge in 0..MAX_PLAUSIBLE_AGE_NANOS) return sensorNanos
        return nowMonoNanos
    }
}
