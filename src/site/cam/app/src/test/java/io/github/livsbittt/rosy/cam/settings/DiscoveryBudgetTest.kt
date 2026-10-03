package io.github.livsbittt.rosy.cam.settings

import org.junit.Assert.*
import org.junit.Test

class DiscoveryBudgetTest {
    @Test fun rediscoveryAndInvalidSightingsCannotGrowWork() {
        val budget = DiscoveryBudget(2)
        assertTrue(budget.claim("one"))
        assertFalse(budget.claim("one"))
        assertTrue(budget.claim("two"))
        assertFalse(budget.claim("three"))
        budget.stop()
        assertFalse(budget.claim("four"))
    }
}
