package io.github.livsbittt.rosy.cam.settings

import org.junit.Assert.*
import org.junit.Test

class DiscoveryBudgetTest {
    @Test fun withdrawnCallbackCannotReviveDeviceAndRediscoveryIsBounded() {
        val budget = DiscoveryBudget(1)
        assertTrue(budget.claim("one"))
        val first = budget.generation("one")
        budget.lost("one")
        assertFalse(budget.current("one", first))
        assertTrue(budget.claim("one"))
        assertFalse(budget.current("one", first))
        assertTrue(budget.current("one", budget.generation("one")))
        repeat(2) { budget.lost("one"); assertTrue(budget.claim("one")) }
        budget.lost("one")
        assertFalse(budget.claim("one"))
        assertFalse(budget.claim("two"))
    }
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
