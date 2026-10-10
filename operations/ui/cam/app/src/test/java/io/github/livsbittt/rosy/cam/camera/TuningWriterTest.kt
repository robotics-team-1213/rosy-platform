package io.github.livsbittt.rosy.cam.camera

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TuningWriterTest {
    /** Records each call; the test answers them in any order. */
    private class FakePort : CameraPort {
        data class Call(val what: String, val value: Any?, val done: (WriteOutcome) -> Unit)
        val calls = mutableListOf<Call>()

        override fun setEv(index: Int, done: (WriteOutcome) -> Unit) { calls += Call("ev", index, done) }
        override fun setOptions(settings: CameraSettings, done: (WriteOutcome) -> Unit) { calls += Call("options", settings, done) }
        override fun clearOptions(done: (WriteOutcome) -> Unit) { calls += Call("clear", null, done) }

        fun answer(what: String, outcome: WriteOutcome = WriteOutcome.OK) {
            val call = calls.first { it.what == what }
            calls.remove(call)
            call.done(outcome)
        }
        fun answerAll() { while (calls.isNotEmpty()) answer(calls.first().what) }
    }

    private val locked = CameraSettings(ev = -10, aeLock = true, awbLock = true, fpsRange = FpsRange(30, 30),
        antibanding = Antibanding.HZ60)
    private val unlocked = locked.copy(aeLock = false, awbLock = false)

    /** Bound, clear confirmed, [goal] written, confirmed and locked; returns the capture count reached. */
    private fun lockedWriter(port: FakePort, w: TuningWriter, goal: CameraSettings): Long {
        w.bind(port, 0)
        port.answerAll()
        w.drive(goal, 0, 1)
        port.answerAll()
        w.drive(goal, 2_000, 2)
        port.answerAll()
        assertEquals(goal, w.confirmed)
        return 2
    }

    @Test
    fun everyBindClearsTheInteropOptionsCameraXKeepsPerCamera() {
        val port = FakePort()
        val w = TuningWriter()
        w.bind(port, 0)
        assertEquals(listOf("clear"), port.calls.map { it.what })
        assertFalse("not reported before the clear is confirmed", w.readyToReport)
        port.answerAll()
        assertTrue(w.readyToReport)
        assertEquals(CameraSettings(), w.written)

        // Lock on the first camera, then rebind (lens switch): the new bind clears again and starts from defaults.
        lockedWriter(port, w, locked)
        val second = FakePort()
        w.unbind()
        w.bind(second, 2)
        assertEquals(listOf("clear"), second.calls.map { it.what })
        assertEquals(CameraSettings(), w.written)
        assertEquals(CameraSettings(), w.confirmed)
    }

    @Test
    fun afterBindTheSettleClockStartsAtTheFirstCapture() {
        val port = FakePort()
        val w = TuningWriter()
        val goal = CameraSettings(aeLock = true)
        w.bind(port, 100)
        port.answerAll()
        // No capture since bind: unlocked however long it takes.
        w.drive(goal, 60_000, 100)
        assertEquals(CameraSettings(), w.written)
        // First capture at t=60 000: the clock starts there.
        w.drive(goal, 60_000, 101)
        w.drive(goal, 60_999, 130)
        assertEquals(CameraSettings(), w.written)
        w.drive(goal, 61_000, 131)
        assertEquals(goal, w.written)
    }

    @Test
    fun torchOnThenOffKeepsTheLocksOffForTheSettleTime() {
        val port = FakePort()
        val w = TuningWriter()
        var frames = lockedWriter(port, w, locked)
        // Torch on at t=10 000: Vision's target drops the AE lock, and the exposure has changed under the AWB lock.
        w.touch(10_000, frames)
        w.drive(locked.copy(aeLock = false), 10_000, frames)
        assertEquals(unlocked, w.written)
        port.answerAll()
        // Torch off at t=10 400: the AE must not re-lock at the torch-lit exposure.
        w.touch(10_400, frames)
        w.drive(locked, 10_400, ++frames)
        w.drive(locked, 11_399, ++frames)
        assertEquals("still unlocked within SETTLE_MS of the torch going off", unlocked, w.written)
        // Settled and a capture after the change: locked again.
        w.drive(locked, 11_400, ++frames)
        assertEquals(locked, w.written)
    }

    @Test
    fun aLockNeedsACaptureAfterTheChange() {
        val port = FakePort()
        val w = TuningWriter()
        val frames = lockedWriter(port, w, locked)
        w.touch(10_000, frames)
        w.drive(locked, 10_000, frames)
        assertEquals(unlocked, w.written)
        port.answerAll()
        w.drive(locked, 20_000, frames)
        assertEquals("no capture since the change, even past the timeout", unlocked, w.written)
        w.drive(locked, 20_001, frames + 1)
        assertEquals(locked, w.written)
    }

    @Test
    fun answersFromAnOlderBindAreDropped() {
        val first = FakePort()
        var settled = 0
        val w = TuningWriter { settled++ }
        w.bind(first, 0)
        first.answerAll()
        w.drive(CameraSettings(ev = -5), 0, 1)
        assertEquals(1, w.inFlight)
        val second = FakePort()
        w.unbind()
        w.bind(second, 1)
        val before = settled
        first.answer("ev")
        assertEquals("stale answer does not touch the count", 1, w.inFlight)
        assertEquals("stale answer does not overwrite confirmed", 0, w.confirmed.ev)
        assertEquals(before, settled)
        second.answer("clear")
        assertEquals(0, w.inFlight)
    }

    @Test
    fun noReportUntilTheLocksHaveSettled() {
        val port = FakePort()
        val w = TuningWriter()
        w.bind(port, 0)
        port.answerAll()
        w.drive(locked, 10_000, 1)
        // Exposure change goes in unlocked; not reportable while in flight nor while the lock still waits.
        assertEquals(unlocked, w.written)
        assertFalse(w.readyToReport)
        port.answerAll()
        w.drive(locked, 10_500, 2)
        assertFalse("confirmed but inside SETTLE_MS", w.readyToReport)
        w.drive(locked, 11_000, 3)
        assertEquals(locked, w.written)
        assertFalse("lock write in flight", w.readyToReport)
        port.answerAll()
        assertTrue(w.readyToReport)
        assertEquals(locked, w.confirmed)
    }

    @Test
    fun aCancelledCallIsNotAFailureAndAFailedControlIsNotRetried() {
        val port = FakePort()
        val w = TuningWriter()
        w.bind(port, 0)
        port.answerAll()
        w.drive(CameraSettings(ev = -3), 0, 1)
        port.answer("ev", WriteOutcome.CANCELLED)
        assertFalse(w.evFailed)
        w.drive(CameraSettings(ev = -4), 10, 2)
        port.answer("ev", WriteOutcome.FAILED)
        assertTrue(w.evFailed)
        w.drive(CameraSettings(ev = -5), 20, 3)
        assertTrue("no EV call after a failure", port.calls.none { it.what == "ev" })
        assertEquals(0, w.confirmed.ev)
        w.clearFailures()
        w.drive(CameraSettings(ev = -6), 30, 4)
        assertEquals(listOf("ev"), port.calls.map { it.what })
    }

    @Test
    fun aDoubleAnswerCountsOnce() {
        val port = FakePort()
        val w = TuningWriter()
        w.bind(port, 0)
        val clear = port.calls.single()
        clear.done(WriteOutcome.OK)
        clear.done(WriteOutcome.OK)
        assertEquals(0, w.inFlight)
    }
}
