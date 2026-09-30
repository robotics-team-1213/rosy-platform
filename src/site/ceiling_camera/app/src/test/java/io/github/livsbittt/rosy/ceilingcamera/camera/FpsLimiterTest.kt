package io.github.livsbittt.rosy.overhead.camera

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FpsLimiterTest {
    private val ms = 1_000_000L

    @Test
    fun firstFrameIsAlwaysAdmitted() {
        assertTrue(FpsLimiter(3.0).tryAdmit(123 * ms))
    }

    @Test
    fun admitsOnlyAfterOneIntervalSinceLastAdmitted() {
        val limiter = FpsLimiter(4.0) // 250 ms
        assertTrue(limiter.tryAdmit(0))
        assertFalse(limiter.tryAdmit(100 * ms))
        assertFalse(limiter.tryAdmit(249 * ms))
        assertTrue(limiter.tryAdmit(250 * ms))
        assertFalse(limiter.tryAdmit(499 * ms))
        assertTrue(limiter.tryAdmit(520 * ms))
    }

    @Test
    fun thirtyFpsCameraIsCutToAtMostThreeFps() {
        val limiter = FpsLimiter(3.0)
        val admitted = (0 until 300).count { limiter.tryAdmit(it * 33_333_333L) } // 10 s at 30 fps
        assertTrue("admitted=$admitted", admitted in 25..30)
    }

    @Test
    fun fpsChangeAppliesToTheNextDecision() {
        val limiter = FpsLimiter(1.0)
        assertTrue(limiter.tryAdmit(0))
        assertFalse(limiter.tryAdmit(500 * ms))
        limiter.fps = 2.0
        assertTrue(limiter.tryAdmit(500 * ms))
        assertEquals(2.0, limiter.fps, 0.0)
    }

    @Test
    fun resetAdmitsImmediately() {
        val limiter = FpsLimiter(1.0)
        assertTrue(limiter.tryAdmit(0))
        limiter.reset()
        assertTrue(limiter.tryAdmit(1 * ms))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsNonPositiveFps() {
        FpsLimiter(0.0)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsNonPositiveFpsAtRuntime() {
        FpsLimiter(1.0).fps = -1.0
    }
}
