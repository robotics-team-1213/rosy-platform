package io.github.livsbittt.rosy.overhead.link

import org.junit.Assert.assertEquals
import org.junit.Test

class RateMeterTest {
    private val s = 1_000_000_000L

    @Test
    fun emptyMeterIsZero() {
        val meter = RateMeter(windowNanos = 2 * s)
        assertEquals(0.0, meter.fps(10 * s), 0.0)
        assertEquals(0.0, meter.kbps(10 * s), 0.0)
    }

    @Test
    fun threeFramesPerSecondOf50kB() {
        val meter = RateMeter(windowNanos = 2 * s)
        for (i in 1..6) meter.record(i * s / 3, 50_000)
        // 6 frames inside the 2 s window ending at 2 s -> 3 fps; 300 kB / 2 s = 1200 kbit/s
        assertEquals(3.0, meter.fps(2 * s), 1e-9)
        assertEquals(1200.0, meter.kbps(2 * s), 1e-9)
    }

    @Test
    fun oldSamplesLeaveTheWindow() {
        val meter = RateMeter(windowNanos = 2 * s)
        meter.record(0, 1000)
        assertEquals(0.0, meter.fps(3 * s), 0.0)
        assertEquals(0.0, meter.kbps(3 * s), 0.0)
    }
}
