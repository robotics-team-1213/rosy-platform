package io.github.livsbittt.rosy.overhead.link

import org.junit.Assert.assertEquals
import org.junit.Test

class BackoffTest {
    @Test
    fun steps1s2s5sThenCaps() {
        val backoff = Backoff()
        assertEquals(listOf(1000L, 2000L, 5000L, 5000L, 5000L), List(5) { backoff.nextDelayMs() })
    }

    @Test
    fun resetOnSuccessStartsOver() {
        val backoff = Backoff()
        backoff.nextDelayMs()
        backoff.nextDelayMs()
        backoff.reset()
        assertEquals(1000L, backoff.nextDelayMs())
    }
}
