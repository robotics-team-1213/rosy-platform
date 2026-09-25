package io.github.livsbittt.rosy.overhead.camera

import org.junit.Assert.assertEquals
import org.junit.Test

class CaptureClockTest {
    private val ms = 1_000_000L

    // Heuristic path: used only when SENSOR_INFO_TIMESTAMP_SOURCE is unavailable.

    @Test
    fun heuristicRealtimeSensorTimestampIsConvertedToMonotonic() {
        // Sensor stamped 40 ms ago on the elapsedRealtime clock (includes deep sleep).
        val mono = CaptureClock.toMonotonic(sensorNanos = 9_960 * ms, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 10_000 * ms)
        assertEquals(4_960 * ms, mono)
    }

    @Test
    fun heuristicMonotonicSensorTimestampIsKept() {
        val mono = CaptureClock.toMonotonic(sensorNanos = 4_970 * ms, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 90_000 * ms)
        assertEquals(4_970 * ms, mono)
    }

    @Test
    fun heuristicImplausibleTimestampFallsBackToArrival() {
        val mono = CaptureClock.toMonotonic(sensorNanos = 42, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 90_000 * ms)
        assertEquals(5_000 * ms, mono)
    }

    @Test
    fun heuristicFutureTimestampFallsBackToArrival() {
        val mono = CaptureClock.toMonotonic(sensorNanos = 5_100 * ms, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 5_050 * ms)
        assertEquals(5_000 * ms, mono)
    }

    // Deterministic paths: the camera reports its timestamp source.

    @Test
    fun realtimeSourceUsesTheElapsedRealtimeBase() {
        val mono = CaptureClock.toMonotonic(
            CaptureClock.Source.REALTIME,
            sensorNanos = 9_960 * ms, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 10_000 * ms,
        )
        assertEquals(4_960 * ms, mono)
    }

    @Test
    fun uptimeSourceIsNotMistakenForRealtimeAfterShortDeepSleep() {
        // Uptime base: sensor 30 ms before now on nanoTime. The device slept 1 s, so the
        // realtime clock is 1 s ahead; the heuristic would read the sensor stamp as 1.03 s old.
        val sensor = 4_970 * ms
        val nowMono = 5_000 * ms
        val nowRealtime = 5_000 * ms + 1_000 * ms
        assertEquals(sensor, CaptureClock.toMonotonic(CaptureClock.Source.UPTIME, sensor, nowMono, nowRealtime))
        // Documents the defect the source lookup avoids.
        assertEquals(nowMono - 1_030 * ms, CaptureClock.toMonotonic(sensor, nowMono, nowRealtime))
    }

    @Test
    fun realtimeSourceIsNotMistakenForUptime() {
        // Realtime base, stamped 20 ms ago; realtime and uptime differ by 1.5 s of deep sleep,
        // which puts the stamp inside the uptime plausibility window too.
        val nowMono = 5_000 * ms
        val nowRealtime = 6_500 * ms
        val sensor = 6_480 * ms
        assertEquals(4_980 * ms, CaptureClock.toMonotonic(CaptureClock.Source.REALTIME, sensor, nowMono, nowRealtime))
    }

    @Test
    fun knownSourceWithImplausibleAgeFallsBackToArrival() {
        val nowMono = 5_000 * ms
        assertEquals(nowMono, CaptureClock.toMonotonic(CaptureClock.Source.UPTIME, 6_000 * ms, nowMono, 9_000 * ms))
        assertEquals(nowMono, CaptureClock.toMonotonic(CaptureClock.Source.REALTIME, 1 * ms, nowMono, 9_000 * ms))
    }

    @Test
    fun unavailableSourceUsesTheHeuristic() {
        val mono = CaptureClock.toMonotonic(
            CaptureClock.Source.UNAVAILABLE,
            sensorNanos = 4_970 * ms, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 90_000 * ms,
        )
        assertEquals(4_970 * ms, mono)
    }

    @Test
    fun camera2ConstantsMapToSources() {
        // CameraMetadata.SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN = 0 (uptime base), _REALTIME = 1.
        assertEquals(CaptureClock.Source.UPTIME, CaptureClock.Source.fromCamera2(0))
        assertEquals(CaptureClock.Source.REALTIME, CaptureClock.Source.fromCamera2(1))
        assertEquals(CaptureClock.Source.UNAVAILABLE, CaptureClock.Source.fromCamera2(null))
        assertEquals(CaptureClock.Source.UNAVAILABLE, CaptureClock.Source.fromCamera2(7))
    }
}
