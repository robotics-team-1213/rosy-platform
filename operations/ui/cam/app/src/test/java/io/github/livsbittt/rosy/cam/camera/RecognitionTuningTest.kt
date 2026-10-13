package io.github.livsbittt.rosy.cam.camera

import io.github.livsbittt.rosy.cam.link.ServerMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RecognitionTuningTest {
    /** Roughly an S21 main camera: index -20..20 at 0.1 EV, both locks, 60 Hz, ranges up to 60 fps. */
    private val s21 = CameraCapabilities(
        evMin = -20, evMax = 20, evStep = 0.1, aeLock = true, awbLock = true, antibanding60 = true,
        fpsRanges = listOf(FpsRange(10, 30), FpsRange(15, 15), FpsRange(15, 30), FpsRange(24, 24), FpsRange(30, 30), FpsRange(60, 60)),
    )
    private val bare = CameraCapabilities()

    private fun req(
        ev: Int = -1, ae: Boolean = true, awb: Boolean = true, maxUs: Long? = 8333, ab: String = "60hz", seq: Long = 1,
    ) = ServerMessage.Camera(seq, ev, ae, awb, maxUs, ab)

    // --- clamping and capability fallbacks ---

    @Test
    fun evIsClampedToMinus2PlusOneEvInsideTheDeviceRange() {
        // 0.1 EV per index: -2.0..+1.0 EV is index -20..10.
        assertEquals(-20, RecognitionTuning.clamp(req(ev = -40), s21).ev)
        assertEquals(10, RecognitionTuning.clamp(req(ev = 19), s21).ev)
        assertEquals(-7, RecognitionTuning.clamp(req(ev = -7), s21).ev)
        // 1/6 EV per index: -12..6, despite 1/6 not being exact in binary.
        val sixth = s21.copy(evMin = -12, evMax = 12, evStep = 1.0 / 6)
        assertEquals(-12 to 6, RecognitionTuning.evIndexBounds(sixth))
        // 1/3 EV: ceil(-6) = -6, floor(3) = 3.
        assertEquals(-6 to 3, RecognitionTuning.evIndexBounds(s21.copy(evMin = -6, evMax = 6, evStep = 1.0 / 3)))
        // 0.3 EV: ceil(-6.67) = -6, floor(3.33) = 3, never beyond the real EV bounds.
        assertEquals(-6 to 3, RecognitionTuning.evIndexBounds(s21.copy(evStep = 0.3)))
        // The device range wins when narrower.
        val narrow = s21.copy(evMin = -2, evMax = 2)
        assertEquals(-2, RecognitionTuning.clamp(req(ev = -6), narrow).ev)
        assertEquals(2, RecognitionTuning.clamp(req(ev = 3), narrow).ev)
    }

    @Test
    fun withoutCompensationEvStaysZero() {
        assertEquals(0, RecognitionTuning.clamp(req(ev = -3), bare).ev)
        assertEquals(0, RecognitionTuning.clamp(req(ev = 2), s21.copy(evStep = 0.0)).ev)
    }

    @Test
    fun unsupportedControlsFallBackToCameraDefaults() {
        val s = RecognitionTuning.clamp(req(), bare)
        assertEquals(CameraSettings(), s)
        assertEquals(Antibanding.AUTO, RecognitionTuning.clamp(req(), s21.copy(antibanding60 = false)).antibanding)
        assertFalse(RecognitionTuning.clamp(req(), s21.copy(aeLock = false)).aeLock)
        assertTrue(RecognitionTuning.clamp(req(), s21.copy(aeLock = false)).awbLock)
    }

    @Test
    fun requestedOffStaysOff() {
        val s = RecognitionTuning.clamp(req(ae = false, awb = false, maxUs = null, ab = "auto"), s21)
        assertEquals(CameraSettings(ev = -1), s)
        assertNull(s.maxExposureUs)
    }

    @Test
    fun exposureCapUsesTheClosestFpsFloorAtMost30Fps() {
        // 1/120 s is out of reach at <= 30 fps: the best is a 30 fps floor (33 333 us), never the 60 fps range.
        val tight = RecognitionTuning.clamp(req(maxUs = 8333), s21)
        assertEquals(FpsRange(30, 30), tight.fpsRange)
        assertEquals(33_333L, tight.maxExposureUs)
        // 1/20 s: the lowest floor that meets it is 24.
        assertEquals(FpsRange(24, 24), RecognitionTuning.clamp(req(maxUs = 50_000), s21).fpsRange)
        // 1/15 s: floor 15, the narrower range first.
        assertEquals(FpsRange(15, 15), RecognitionTuning.clamp(req(maxUs = 66_667), s21).fpsRange)
        assertNull(RecognitionTuning.clamp(req(maxUs = 8333), s21.copy(fpsRanges = listOf(FpsRange(60, 60)))).fpsRange)
        assertNull(RecognitionTuning.clamp(req(maxUs = 8333), bare).fpsRange)
    }

    @Test
    fun aReportedCapSentBackPicksTheSameRange() {
        for (range in listOf(FpsRange(30, 30), FpsRange(15, 15), FpsRange(24, 24))) {
            val echoed = capUs(range)
            assertEquals("cap $echoed", echoed, RecognitionTuning.clamp(req(maxUs = echoed), s21).maxExposureUs)
        }
        assertEquals(FpsRange(30, 30), RecognitionTuning.clamp(req(maxUs = 33_333), s21).fpsRange)
        assertEquals(FpsRange(15, 15), RecognitionTuning.clamp(req(maxUs = 66_666), s21).fpsRange)
    }

    @Test
    fun supportedReportsTheShortestReachableCap() {
        val s = s21.supported()
        assertEquals(-20, s.evMin)
        assertEquals(0.1, s.evStep, 0.0)
        assertEquals(33_333L, s.maxExposureUs)
        assertTrue(s.antibanding60hz)
        assertNull(bare.supported().maxExposureUs)
    }

    // --- precedence and timeouts (fake clock) ---

    @Test
    fun freshVisionRulesForSixtySecondsThenLocalTakesOver() {
        val t = RecognitionTuning()
        assertEquals(TuningMode.LOCAL, t.mode(0))
        assertEquals(RecognitionTuning.Receipt.APPLIED, t.receive(req(seq = 5), 1_000))
        assertEquals(TuningMode.VISION, t.mode(1_000))
        assertEquals(TuningMode.VISION, t.mode(61_000))
        assertEquals(TuningMode.LOCAL, t.mode(61_001))
        assertEquals(5L, t.lastSeq)
        val target = t.target(TuningMode.VISION, s21, CameraSettings(), localEv = 2)
        assertEquals(-1, target.ev)
        assertTrue(target.aeLock)
        assertEquals(CameraSettings(ev = 2), t.target(TuningMode.LOCAL, s21, target, localEv = 2))
    }

    @Test
    fun newestEarlyRequestAppliesAfterTheGap() {
        val t = RecognitionTuning()
        t.receive(req(seq = 1, ev = -1), 0)
        assertEquals(RecognitionTuning.Receipt.TOO_SOON, t.receive(req(seq = 2, ev = 3), 100))
        assertEquals(RecognitionTuning.Receipt.TOO_SOON, t.receive(req(seq = 3, ev = 2), 400))
        assertEquals("a waiting request is not echoed yet", 1L, t.lastSeq)
        assertEquals(-1, t.target(TuningMode.VISION, s21, CameraSettings(), 0).ev)
        assertFalse(t.tick(499))
        assertTrue(t.tick(500))
        assertEquals(3L, t.lastSeq)
        assertEquals(2, t.target(TuningMode.VISION, s21, CameraSettings(), 0).ev)
        assertFalse("nothing left waiting", t.tick(10_000))
        // The applied pending request restarts the gap and the 60 s window.
        assertEquals(RecognitionTuning.Receipt.TOO_SOON, t.receive(req(seq = 4), 900))
        assertEquals(TuningMode.VISION, t.mode(60_500))
    }

    @Test
    fun switchingOffDropsAWaitingRequest() {
        val t = RecognitionTuning()
        t.receive(req(seq = 1), 0)
        t.receive(req(seq = 2), 100)
        t.setEnabled(false)
        t.setEnabled(true)
        assertFalse(t.tick(1_000))
        assertEquals(TuningMode.LOCAL, t.mode(1_000))
    }

    @Test
    fun torchLightNeverGetsAnAeLock() {
        val t = RecognitionTuning()
        t.receive(req(), 0)
        val lit = t.target(TuningMode.VISION, s21, CameraSettings(), 0, torchOn = true)
        assertFalse(lit.aeLock)
        assertTrue(lit.awbLock)
        assertTrue(t.target(TuningMode.VISION, s21, CameraSettings(), 0, torchOn = false).aeLock)
    }

    @Test
    fun aNewMessageRestartsTheWindow() {
        val t = RecognitionTuning()
        t.receive(req(seq = 1), 0)
        t.receive(req(seq = 2, ev = 1), 50_000)
        assertEquals(TuningMode.VISION, t.mode(100_000))
        assertEquals(1, t.target(TuningMode.VISION, s21, CameraSettings(), 0).ev)
    }

    @Test
    fun clockGoingBackwardsMakesTheRequestStale() {
        val t = RecognitionTuning()
        t.receive(req(), 10_000)
        assertEquals(TuningMode.LOCAL, t.mode(9_999))
    }

    @Test
    fun switchOffIgnoresMessagesAndForgetsTheLastOne() {
        val t = RecognitionTuning()
        t.receive(req(seq = 1), 0)
        t.setEnabled(false)
        assertEquals(TuningMode.DISABLED, t.mode(1))
        assertEquals(RecognitionTuning.Receipt.IGNORED_SWITCH_OFF, t.receive(req(seq = 2), 2))
        assertEquals("ignored messages are still echoed", 2L, t.lastSeq)
        assertEquals(CameraSettings(ev = 1), t.target(TuningMode.DISABLED, s21, CameraSettings(ev = -1, aeLock = true), 1))
        t.setEnabled(true)
        assertEquals("a request from before the switch went off never comes back", TuningMode.LOCAL, t.mode(3))
    }

    // --- thermal hold ---

    @Test
    fun severeHeatHoldsTheLastSettingsAndIgnoresNewRequestsUntilItCools() {
        val t = RecognitionTuning()
        t.receive(req(ev = -1), 0)
        val locked = t.target(TuningMode.VISION, s21, CameraSettings(), 0)
        t.thermal = 3
        t.receive(req(ev = 2, ae = false, awb = false), 1_000)
        assertEquals(TuningMode.THERMAL_HOLD, t.mode(1_000))
        assertEquals(locked, t.target(TuningMode.THERMAL_HOLD, s21, locked, 0))
        // The Vision window runs out while hot: still held, never unlocked.
        assertEquals(TuningMode.THERMAL_HOLD, t.mode(200_000))
        t.thermal = 4
        assertEquals(TuningMode.THERMAL_HOLD, t.mode(200_000))
        // The operator's switch wins over the hold: off releases to defaults even while hot.
        t.setEnabled(false)
        assertEquals(TuningMode.DISABLED, t.mode(200_000))
        assertEquals(CameraSettings(), t.target(TuningMode.DISABLED, s21, locked, 0))
        t.setEnabled(true)
        assertEquals(TuningMode.THERMAL_HOLD, t.mode(200_000))
        t.thermal = 2
        t.receive(req(ev = 2, ae = false, awb = false), 201_000)
        assertEquals(TuningMode.VISION, t.mode(201_000))
        assertEquals(CameraSettings(ev = 2, fpsRange = FpsRange(30, 30), antibanding = Antibanding.HZ60),
            t.target(TuningMode.VISION, s21, locked, 0))
    }

    @Test
    fun moderateHeatDoesNotHold() {
        val t = RecognitionTuning()
        t.thermal = 2
        t.receive(req(), 0)
        assertEquals(TuningMode.VISION, t.mode(0))
    }

    // --- exposure change first, locks after it is confirmed and settled ---

    @Test
    fun locksWaitForTheConfirmedChangeAndTheSettleTime() {
        val goal = CameraSettings(ev = -10, aeLock = true, awbLock = true)
        val first = RecognitionTuning.step(CameraSettings(), CameraSettings(), goal, null, 0)
        assertEquals(CameraSettings(ev = -10), first)
        // Written at t=0 but not confirmed: unlocked even after SETTLE_MS.
        assertEquals(first, RecognitionTuning.step(first, CameraSettings(), goal, 0, 2_000))
        // Confirmed: unlocked inside SETTLE_MS, locked after it.
        assertEquals(first, RecognitionTuning.step(first, first, goal, 0, 999))
        assertEquals(goal, RecognitionTuning.step(first, first, goal, 0, RecognitionTuning.SETTLE_MS))
        // Never confirmed: locked at the timeout anyway.
        assertEquals(goal, RecognitionTuning.step(first, CameraSettings(), goal, 0, RecognitionTuning.SETTLE_TIMEOUT_MS))
    }

    @Test
    fun capAndAntibandingChangesSettleLikeEv() {
        val locked = CameraSettings(ev = -1, aeLock = true, awbLock = true)
        val capped = locked.copy(fpsRange = FpsRange(30, 30))
        assertEquals(capped.copy(aeLock = false, awbLock = false), RecognitionTuning.step(locked, locked, capped, 0, 600_000))
        val banded = locked.copy(antibanding = Antibanding.HZ60)
        assertEquals(banded.copy(aeLock = false, awbLock = false), RecognitionTuning.step(locked, locked, banded, 0, 600_000))
    }

    @Test
    fun aLockedCameraUnlocksToMoveEv() {
        val locked = CameraSettings(ev = -1, aeLock = true, awbLock = true)
        val next = locked.copy(ev = -2)
        assertEquals(CameraSettings(ev = -2), RecognitionTuning.step(locked, locked, next, 0, 600_000))
    }

    @Test
    fun aBindStartsTheSettleClock() {
        // At bind nothing changes, but the lock still waits SETTLE_MS from the bind time.
        val goal = CameraSettings(aeLock = true)
        assertEquals(CameraSettings(), RecognitionTuning.step(CameraSettings(), CameraSettings(), goal, 5_000, 5_500))
        assertEquals(goal, RecognitionTuning.step(CameraSettings(), CameraSettings(), goal, 5_000, 6_000))
        // No capture since the change (or since bind): never locked, not even at the timeout.
        assertEquals(CameraSettings(), RecognitionTuning.step(CameraSettings(), CameraSettings(), goal, null, 60_000))
        assertEquals(CameraSettings(), RecognitionTuning.step(CameraSettings(), CameraSettings(), goal, 0, 60_000, framed = false))
    }

    @Test
    fun noSettleWhenNothingIsLockedOrNothingChanges() {
        val unlocked = CameraSettings(ev = 2, antibanding = Antibanding.HZ60)
        assertEquals(unlocked, RecognitionTuning.step(CameraSettings(), CameraSettings(), unlocked, null, 0))
        val locked = CameraSettings(ev = -1, aeLock = true)
        assertEquals(locked, RecognitionTuning.step(locked, locked, locked, 0, 600_000))
        // Unchanged goal but a recent outside change (torch): unlocked until it settles.
        assertEquals(CameraSettings(ev = -1), RecognitionTuning.step(locked, locked, locked, 600_000, 600_500))
    }

    @Test
    fun evTextShowsRealEvWithARealMinusSign() {
        assertEquals("EV −1.0", TuningStatus(applied = CameraSettings(ev = -10), evStep = 0.1).evText)
        assertEquals("EV 0.0", TuningStatus(evStep = 0.1).evText)
        assertEquals("EV +0.5", TuningStatus(applied = CameraSettings(ev = 3), evStep = 1.0 / 6).evText)
        assertEquals("EV 0.0", TuningStatus(applied = CameraSettings(ev = 3), evStep = 0.0).evText)
    }

    @Test
    fun appliedCarriesModeAndCap() {
        val a = CameraSettings(ev = -1, aeLock = true, fpsRange = FpsRange(30, 30), antibanding = Antibanding.HZ60)
            .applied(TuningMode.VISION)
        assertEquals("vision", a.mode)
        assertEquals("60hz", a.antibanding)
        assertEquals(33_333L, a.maxExposureUs)
    }
}
