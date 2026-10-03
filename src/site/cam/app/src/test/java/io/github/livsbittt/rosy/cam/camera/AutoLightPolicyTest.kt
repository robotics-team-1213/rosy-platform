package io.github.livsbittt.rosy.cam.camera

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AutoLightPolicyTest {
    private val policy = AutoLightPolicy()

    private fun update(luma: Int, time: Long, torch: Boolean = false) =
        policy.update(luma, time, enabled = true, supported = true,
            thermalBlocked = false, torchOn = torch)

    private fun turnOn() {
        assertFalse(update(28, 0))
        assertTrue(update(28, 2000))
    }

    @Test fun brightStaysOff() {
        assertFalse(update(29, 0))
        assertFalse(update(255, 3000))
    }

    @Test fun briefDarkDoesNotTurnOn() {
        assertFalse(update(28, 0))
        assertFalse(update(28, 1999))
        assertFalse(update(29, 2000))
        assertFalse(update(0, 3000))
        assertFalse(update(0, 4999))
        assertTrue(update(0, 5000))
    }

    @Test fun sustainedDarkTurnsOnAtTwoSeconds() {
        turnOn()
    }

    @Test fun ownLightDoesNotCountAsAmbient() {
        turnOn()
        assertTrue(update(255, 2500, torch = true))
        assertTrue(update(255, 31999, torch = true))
        assertFalse(update(255, 32000, torch = true))
    }

    @Test fun cooldownRequiresFreshDarkWindow() {
        turnOn()
        assertFalse(update(0, 32000, torch = true))
        assertFalse(update(0, 41999))
        assertFalse(update(0, 42000))
        assertFalse(update(0, 43999))
        assertTrue(update(0, 44000))
    }

    @Test fun unconfirmedOffCannotRestartBudget() {
        turnOn()
        assertFalse(update(0, 32000, torch = true))
        assertFalse(update(0, 42000, torch = true))
        assertFalse(update(0, 50000, torch = true))
        assertFalse(update(0, 50001))
        assertTrue(update(0, 52001))
    }

    @Test fun thermalBlockTurnsOffImmediately() {
        turnOn()
        assertFalse(policy.update(0, 2500, true, true, true, true))
    }

    @Test fun thermalBlockClearsPendingDark() {
        assertFalse(update(0, 0))
        assertFalse(policy.update(0, 2000, true, true, true, false))
        assertFalse(update(0, 2001))
        assertTrue(update(0, 4001))
    }

    @Test fun existingTorchFramesAreAlsoBounded() {
        assertTrue(update(255, 1000, torch = true))
        assertTrue(update(255, 30999, torch = true))
        assertFalse(update(255, 31000, torch = true))
    }

    @Test fun disabledAndUnsupportedClearDarkWindow() {
        for (enabled in listOf(false, true)) {
            policy.reset()
            assertFalse(update(0, 0))
            assertFalse(policy.update(0, 2000, enabled, !enabled, false, false))
            assertFalse(update(0, 2001))
            assertTrue(update(0, 4001))
            assertFalse(policy.update(0, 4002, enabled, !enabled, false, true))
        }
    }

    @Test fun reversedClockResetsAndTurnsOff() {
        turnOn()
        assertFalse(update(0, 1000, torch = true))
        assertFalse(update(0, 1001))
        assertTrue(update(0, 3001))
    }

    @Test fun resetClearsSessionHistory() {
        turnOn()
        policy.reset(10000)
        assertFalse(update(0, 10000))
        assertTrue(update(0, 12000))
    }
}
