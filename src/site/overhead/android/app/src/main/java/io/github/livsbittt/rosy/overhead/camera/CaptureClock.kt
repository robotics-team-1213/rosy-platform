package io.github.livsbittt.rosy.overhead.camera

/**
 * Maps a camera sensor timestamp onto the System.nanoTime clock so age_ms includes the
 * capture-to-analyzer delay.
 *
 * The sensor timebase is given by CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE:
 * REALTIME means SystemClock.elapsedRealtimeNanos (counts deep sleep), UNKNOWN means the
 * uptime/System.nanoTime base. When the source is known the conversion is deterministic.
 * Only when the characteristic cannot be read do we guess from which base gives a plausible age.
 * Any implausible age (negative or > 2 s) falls back to the arrival time.
 */
object CaptureClock {
    private const val MAX_PLAUSIBLE_AGE_NANOS = 2_000_000_000L

    enum class Source {
        /** SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME: elapsedRealtimeNanos base. */
        REALTIME,

        /** SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN: uptime base, same as System.nanoTime. */
        UPTIME,

        /** The characteristic could not be read; use the plausibility heuristic. */
        UNAVAILABLE;

        companion object {
            // Values of CameraMetadata.SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN / _REALTIME, kept
            // literal so this stays free of android.* imports.
            private const val CAMERA2_UNKNOWN = 0
            private const val CAMERA2_REALTIME = 1

            fun fromCamera2(value: Int?): Source = when (value) {
                CAMERA2_REALTIME -> REALTIME
                CAMERA2_UNKNOWN -> UPTIME
                else -> UNAVAILABLE
            }
        }
    }

    fun toMonotonic(source: Source, sensorNanos: Long, nowMonoNanos: Long, nowRealtimeNanos: Long): Long =
        when (source) {
            Source.REALTIME -> {
                val age = nowRealtimeNanos - sensorNanos
                if (age in 0..MAX_PLAUSIBLE_AGE_NANOS) nowMonoNanos - age else nowMonoNanos
            }
            Source.UPTIME -> {
                val age = nowMonoNanos - sensorNanos
                if (age in 0..MAX_PLAUSIBLE_AGE_NANOS) sensorNanos else nowMonoNanos
            }
            Source.UNAVAILABLE -> toMonotonic(sensorNanos, nowMonoNanos, nowRealtimeNanos)
        }

    /**
     * Heuristic for an unknown timebase: tries the realtime reading first, then uptime. On an
     * uptime-based sensor this overstates the age by the deep-sleep time when that is under 2 s,
     * which is why [Source] is used whenever the camera reports it.
     */
    fun toMonotonic(sensorNanos: Long, nowMonoNanos: Long, nowRealtimeNanos: Long): Long {
        val realtimeAge = nowRealtimeNanos - sensorNanos
        if (realtimeAge in 0..MAX_PLAUSIBLE_AGE_NANOS) return nowMonoNanos - realtimeAge
        val monoAge = nowMonoNanos - sensorNanos
        if (monoAge in 0..MAX_PLAUSIBLE_AGE_NANOS) return sensorNanos
        return nowMonoNanos
    }
}
