package io.github.livsbittt.rosy.cam.health

import org.junit.Assert.*
import org.junit.Test

class ScreenCoolingPolicyTest {
    private fun health(thermal: Int, temperature: Double? = null) = DeviceHealth(80, false, temperature, thermal)
    @Test fun unknownEvidenceNeverTurnsOffTheScreen() {
        val policy = ScreenCoolingPolicy()
        assertFalse(policy.requestSleep(null))
        assertFalse(policy.requestSleep(health(-1)))
    }
    @Test fun thermalStatusTakesPrecedenceAndRepeatedHeatDoesNotRelock() {
        val policy = ScreenCoolingPolicy()
        assertFalse(policy.requestSleep(health(2, 60.0)))
        assertTrue(policy.requestSleep(health(3)))
        assertTrue(policy.coolingRequired)
        assertFalse(policy.requestSleep(health(4)))
        assertFalse(policy.requestSleep(health(2)))
        assertFalse(policy.requestSleep(health(3)))
        assertFalse(policy.requestSleep(health(1)))
        assertFalse(policy.coolingRequired)
        assertTrue(policy.requestSleep(health(3)))
    }
    @Test fun oldDevicesUseBatteryTemperatureWithRecoveryHysteresis() {
        val policy = ScreenCoolingPolicy()
        assertTrue(policy.requestSleep(health(-1, 45.0)))
        assertFalse(policy.requestSleep(health(-1, 43.0)))
        assertFalse(policy.requestSleep(health(-1, 46.0)))
        assertFalse(policy.requestSleep(health(-1, 41.0)))
        assertTrue(policy.requestSleep(health(-1, 45.0)))
    }
}
