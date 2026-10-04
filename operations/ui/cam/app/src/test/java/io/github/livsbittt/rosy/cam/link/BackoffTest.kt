package io.github.livsbittt.rosy.cam.link

import org.junit.Assert.assertEquals
import org.junit.Test

class BackoffTest {
    @Test
    fun steps1s2s5sThenCaps() {
        val backoff = Backoff(random = { 1.0 })
        assertEquals(listOf(1000L, 2000L, 5000L, 5000L, 5000L), List(5) { backoff.nextDelayMs() })
    }

    @Test
    fun resetOnSuccessStartsOver() {
        val backoff = Backoff(random = { 1.0 })
        backoff.nextDelayMs()
        backoff.nextDelayMs()
        backoff.reset()
        assertEquals(1000L, backoff.nextDelayMs())
    }

    @Test fun jitterHasNonzeroFloorAndHardCap() {
        val backoff = Backoff(random = { 0.0 })
        assertEquals(listOf(800L, 1600L, 4000L, 4000L), List(4) { backoff.nextDelayMs() })
    }
}
