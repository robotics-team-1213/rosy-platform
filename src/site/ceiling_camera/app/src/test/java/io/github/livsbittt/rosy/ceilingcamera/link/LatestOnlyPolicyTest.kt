package io.github.livsbittt.rosy.overhead.link

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LatestOnlyPolicyTest {
    @Test
    fun admitsWhenNothingIsQueued() {
        val policy = LatestOnlyPolicy()
        assertTrue(policy.admit(queuedBytes = 0))
        assertEquals(0L, policy.dropped)
    }

    @Test
    fun dropsAndCountsWhileASendIsInFlight() {
        val policy = LatestOnlyPolicy()
        assertFalse(policy.admit(queuedBytes = 60_000))
        assertFalse(policy.admit(queuedBytes = 1))
        assertTrue(policy.admit(queuedBytes = 0))
        assertEquals(2L, policy.dropped)
    }

    @Test
    fun otherDropsAreCountedTooAndResettable() {
        val policy = LatestOnlyPolicy()
        policy.countDrop()
        assertEquals(1L, policy.dropped)
        policy.resetCount()
        assertEquals(0L, policy.dropped)
    }
}
