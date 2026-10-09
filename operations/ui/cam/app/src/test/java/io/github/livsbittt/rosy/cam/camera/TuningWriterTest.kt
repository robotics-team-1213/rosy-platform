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
        w.drive(locked, 0)
        port.answerAll()
        w.drive(locked, 5_000)
        port.answerAll()
        assertEquals(locked, w.confirmed)
        val second = FakePort()
        w.unbind()
        w.bind(second, 6_000)
        assertEquals(listOf("clear"), second.calls.map { it.what })
        assertEquals(CameraSettings(), w.written)
        assertEquals(CameraSettings(), w.confirmed)
    }

    @Test
    fun answersFromAnOlderBindAreDropped() {
        val first = FakePort()
        var settled = 0
        val w = TuningWriter { settled++ }
        w.bind(first, 0)
        first.answerAll()
        w.drive(CameraSettings(ev = -5), 0)
        assertEquals(1, w.inFlight)
        val second = FakePort()
        w.unbind()
        w.bind(second, 100)
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
        w.drive(locked, 10_000)
        // Exposure change goes in unlocked; not reportable while in flight nor while the lock still waits.
        assertEquals(locked.copy(aeLock = false, awbLock = false), w.written)
        assertFalse(w.readyToReport)
        port.answerAll()
        w.drive(locked, 10_500)
        assertFalse("confirmed but inside SETTLE_MS", w.readyToReport)
        w.drive(locked, 11_000)
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
        w.drive(CameraSettings(ev = -3), 0)
        port.answer("ev", WriteOutcome.CANCELLED)
        assertFalse(w.evFailed)
        w.drive(CameraSettings(ev = -4), 10)
        port.answer("ev", WriteOutcome.FAILED)
        assertTrue(w.evFailed)
        w.drive(CameraSettings(ev = -5), 20)
        assertTrue("no EV call after a failure", port.calls.none { it.what == "ev" })
        assertEquals(0, w.confirmed.ev)
        w.clearFailures()
        w.drive(CameraSettings(ev = -6), 30)
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
