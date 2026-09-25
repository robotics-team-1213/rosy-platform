package io.github.livsbittt.rosy.overhead.camera

import org.junit.Assert.assertEquals
import org.junit.Test

class CaptureClockTest {
    private val ms = 1_000_000L

    @Test
    fun realtimeSensorTimestampIsConvertedToMonotonic() {
        // Sensor stamped 40 ms ago on the elapsedRealtime clock (includes deep sleep).
        val mono = CaptureClock.toMonotonic(sensorNanos = 9_960 * ms, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 10_000 * ms)
        assertEquals(4_960 * ms, mono)
    }

    @Test
    fun monotonicSensorTimestampIsKept() {
        val mono = CaptureClock.toMonotonic(sensorNanos = 4_970 * ms, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 90_000 * ms)
        assertEquals(4_970 * ms, mono)
    }

    @Test
    fun implausibleTimestampFallsBackToArrival() {
        val mono = CaptureClock.toMonotonic(sensorNanos = 42, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 90_000 * ms)
        assertEquals(5_000 * ms, mono)
    }

    @Test
    fun futureTimestampFallsBackToArrival() {
        val mono = CaptureClock.toMonotonic(sensorNanos = 5_100 * ms, nowMonoNanos = 5_000 * ms, nowRealtimeNanos = 5_050 * ms)
        assertEquals(5_000 * ms, mono)
    }
}
