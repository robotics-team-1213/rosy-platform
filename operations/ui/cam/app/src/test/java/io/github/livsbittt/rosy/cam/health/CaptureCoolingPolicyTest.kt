package io.github.livsbittt.rosy.cam.health

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureCoolingPolicyTest {
    private fun health(thermal: Int, temperature: Double? = null) = DeviceHealth(80, true, temperature, thermal)

    @Test
    fun aWatchingRequestDoesNotKeepASeverePhoneCapturing() {
        val policy = CaptureCoolingPolicy()
        assertFalse(policy.paused(null))
        assertFalse(policy.paused(health(2, 60.0)))
        assertTrue(policy.paused(health(3, 36.0)))
        assertTrue(policy.paused(health(2, 36.0)))
        assertFalse(policy.paused(health(1, 36.0)))
        assertTrue(policy.paused(health(4)))
    }

    @Test
    fun batteryTemperatureIsTheFallbackAndHoldsUntilCool() {
        val policy = CaptureCoolingPolicy()
        assertFalse(policy.paused(health(-1, 44.9)))
        assertTrue(policy.paused(health(-1, 45.0)))
        assertTrue(policy.paused(null))
        assertTrue(policy.paused(health(-1, 42.0)))
        assertFalse(policy.paused(health(-1, 41.0)))
    }
}
