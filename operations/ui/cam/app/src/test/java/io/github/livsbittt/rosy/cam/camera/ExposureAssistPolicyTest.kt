package io.github.livsbittt.rosy.cam.camera

import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class ExposureAssistPolicyTest {
    private val bright = LumaStats(0.5, 0.0, 200.0)
    private val dark = LumaStats(0.0, 0.5, 20.0)
    private val ok = LumaStats(0.0, 0.0, 120.0)
    private fun policy() = ExposureAssistPolicy(stepIndex = 2, limitIndex = 6)

    @Test fun offStaysZero() {
        val p = policy()
        assertEquals(0, p.update(bright, 0, enabled = false, blocked = false))
        assertEquals(0, p.update(bright, 10_000, enabled = false, blocked = false))
    }

    @Test fun dwellBeforeFirstStepThenMinGap() {
        val p = policy()
        assertEquals(0, p.update(bright, 0, true, false))
        assertEquals(0, p.update(bright, 2_999, true, false))
        assertEquals(-2, p.update(bright, 3_000, true, false))
        assertEquals(-2, p.update(bright, 6_999, true, false))
        assertEquals(-4, p.update(bright, 7_000, true, false))
    }

    @Test fun neverPastLimit() {
        val p = policy()
        var t = 0L
        repeat(40) { p.update(bright, t, true, false); t += 1000 }
        assertEquals(-6, p.index)
        val q = policy()
        t = 0
        repeat(40) { q.update(dark, t, true, false); t += 1000 }
        assertEquals(6, q.index)
    }

    @Test fun glareShorterThanDwellNeverMoves() {
        val p = policy()
        p.update(bright, 0, true, false)
        p.update(bright, 2_000, true, false)
        p.update(ok, 2_500, true, false)
        p.update(bright, 3_000, true, false)
        assertEquals(0, p.update(bright, 5_000, true, false))
    }

    @Test fun hysteresisHoldsVerdictBetweenThresholds() {
        val p = policy()
        p.update(bright, 0, true, false)
        p.update(LumaStats(0.15, 0.0, 150.0), 100, true, false)
        assertEquals(ExposureVerdict.OVER, p.verdict)
        p.update(LumaStats(0.05, 0.0, 150.0), 200, true, false)
        assertEquals(ExposureVerdict.OK, p.verdict)
        p.update(LumaStats(0.15, 0.0, 150.0), 300, true, false)
        assertEquals(ExposureVerdict.OK, p.verdict)
    }

    @Test fun correctionIsNotUndoneByTime() {
        val p = policy()
        p.update(bright, 0, true, false)
        p.update(bright, 3_000, true, false)
        p.update(ok, 4_000, true, false)
        assertEquals(-2, p.update(ok, 600_000, true, false))
    }

    @Test fun blockedOrNoSampleHoldsIndex() {
        val p = policy()
        p.update(bright, 0, true, false)
        p.update(bright, 3_000, true, false)
        assertEquals(-2, p.update(bright, 20_000, true, blocked = true))
        assertEquals(-2, p.update(null, 30_000, true, false))
    }

    @Test fun clockGoingBackwardsResets() {
        val p = policy()
        p.update(bright, 0, true, false)
        p.update(bright, 3_000, true, false)
        assertEquals(0, p.update(bright, 1_000, true, false))
    }

    @Test fun statsCountClipAndCrushInsideInsetOnly() {
        val w = 100
        val h = 100
        val edge = ByteArray(w * h) { 128.toByte() }
        for (y in 0 until h) for (x in 0 until 5) edge[y * w + x] = 255.toByte()
        assertEquals(0.0, LumaStats.measure(ByteBuffer.wrap(edge), w, 1, 0, 0, w, h)!!.clip, 1e-9)
        val half = ByteArray(w * h) { if (it % w < 50) 255.toByte() else 0 }
        val m = LumaStats.measure(ByteBuffer.wrap(half), w, 1, 0, 0, w, h)!!
        assertEquals(0.5, m.clip, 0.08)
        assertEquals(0.5, m.crush, 0.08)
        assertNull(LumaStats.measure(ByteBuffer.allocate(10), w, 1, 0, 0, w, h))
    }
}
