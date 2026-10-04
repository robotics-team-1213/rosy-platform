package io.github.livsbittt.rosy.cam.camera

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AdaptiveJpegQualityTest {
    @Test
    fun startsAtTheConfiguredQuality() {
        assertEquals(70, AdaptiveJpegQuality().start(70))
    }

    @Test
    fun oversizeStepsDownUntilTheFloorThenGivesUp() {
        val q = AdaptiveJpegQuality()
        q.start(70)
        assertEquals(60, q.retryAfterOversize())
        assertEquals(50, q.retryAfterOversize())
        assertNull("only two retries per frame", q.retryAfterOversize())
    }

    @Test
    fun neverRetriesBelowTheFloor() {
        val q = AdaptiveJpegQuality()
        q.start(35)
        assertEquals(AdaptiveJpegQuality.FLOOR, q.retryAfterOversize())
        assertNull(q.retryAfterOversize())
    }

    @Test
    fun nextFrameStartsAtTheLastQualityThatFit() {
        val q = AdaptiveJpegQuality()
        q.start(70)
        q.retryAfterOversize()
        q.encoded()
        assertEquals(60, q.start(70))
    }

    @Test
    fun climbsBackTowardTheConfiguredQualityAfterASteadyRun() {
        val q = AdaptiveJpegQuality()
        q.start(70)
        q.retryAfterOversize()
        q.retryAfterOversize()
        q.encoded() // settled at 50; this fit counts toward the run
        repeat(AdaptiveJpegQuality.RECOVER_AFTER - 1) {
            assertEquals(50, q.start(70))
            q.encoded()
        }
        assertEquals(55, q.start(70))
    }

    @Test
    fun oversizeRecoveryProbeReturnsToTheLastQualityThatFit() {
        val q = AdaptiveJpegQuality()
        q.start(70)
        q.retryAfterOversize()
        q.retryAfterOversize()
        q.encoded() // settled at 50
        repeat(AdaptiveJpegQuality.RECOVER_AFTER - 1) { q.start(70); q.encoded() }
        assertEquals(55, q.start(70))
        assertEquals("no sawtooth below the last fit", 50, q.retryAfterOversize())
    }

    @Test
    fun afterADropTheNextFrameStartsAtTheLowestQualityTried() {
        val q = AdaptiveJpegQuality()
        q.start(70)
        q.retryAfterOversize()
        q.retryAfterOversize()
        assertNull(q.retryAfterOversize()) // dropped
        assertEquals(50, q.start(70))
    }

    @Test
    fun aConfiguredQualityAtTheFloorIsNeverRetried() {
        val q = AdaptiveJpegQuality()
        assertEquals(30, q.start(30))
        assertNull(q.retryAfterOversize())
    }

    @Test
    fun resetForgetsTheAdaptation() {
        val q = AdaptiveJpegQuality()
        q.start(70)
        q.retryAfterOversize()
        q.encoded()
        q.reset()
        assertEquals(70, q.start(70))
    }

    @Test
    fun configuredQualityIsACeiling() {
        val q = AdaptiveJpegQuality()
        repeat(100) { q.start(70); q.encoded() }
        assertEquals(70, q.start(70))
        assertEquals("a lowered config applies at once", 40, q.start(40))
    }

    @Test
    fun lastFitReportsTheQualityActuallySent() {
        val q = AdaptiveJpegQuality()
        assertNull(q.lastFit)
        q.start(70)
        q.retryAfterOversize()
        q.encoded()
        assertEquals(60, q.lastFit)
        q.start(70)
        q.retryAfterOversize()
        q.retryAfterOversize()
        assertEquals("a dropped frame does not change what was last sent", 60, q.lastFit)
    }
}
