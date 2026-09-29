package io.github.livsbittt.rosy.overhead.health

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceHealthTest {
    @Test
    fun parsesBatteryExtras() {
        // S21 on 2026-09-30: level 56/100, AC, 36.6 °C.
        val h = DeviceHealth.fromBatteryExtras(level = 56, scale = 100, status = 2, plugged = 1, temperatureTenths = 366, thermalStatus = 0)
        assertEquals(56, h.batteryPct)
        assertTrue(h.charging)
        assertEquals(36.6, h.temperatureC!!, 1e-9)
        assertTrue(h.warnings.isEmpty())
    }

    @Test
    fun missingValuesBecomeNull() {
        val h = DeviceHealth.fromBatteryExtras(-1, -1, 1, 0, DeviceHealth.NO_TEMPERATURE, DeviceHealth.THERMAL_UNKNOWN)
        assertNull(h.batteryPct)
        assertNull(h.temperatureC)
        assertFalse(h.charging)
        assertTrue(h.warnings.isEmpty())
    }

    @Test
    fun lowBatteryWarnsOnlyWhenNotCharging() {
        assertEquals(listOf(HealthWarning.BATTERY_LOW), DeviceHealth(19, charging = false, temperatureC = 30.0, thermalStatus = 0).warnings)
        assertTrue(DeviceHealth(19, charging = true, temperatureC = 30.0, thermalStatus = 0).warnings.isEmpty())
        assertTrue(DeviceHealth(20, charging = false, temperatureC = 30.0, thermalStatus = 0).warnings.isEmpty())
    }

    @Test
    fun hotFromThermalStatusModerateOrAbove() {
        assertTrue(DeviceHealth(80, true, 39.0, thermalStatus = 1).warnings.isEmpty())
        assertEquals(listOf(HealthWarning.HOT), DeviceHealth(80, true, 39.0, thermalStatus = 2).warnings)
        assertEquals(listOf(HealthWarning.HOT, HealthWarning.BATTERY_LOW), DeviceHealth(10, false, 30.0, thermalStatus = 4).warnings)
    }

    @Test
    fun withoutThermalStatusFallsBackToBatteryTemperature() {
        assertTrue(DeviceHealth(80, true, 42.9).warnings.isEmpty())
        assertEquals(listOf(HealthWarning.HOT), DeviceHealth(80, true, 43.0).warnings)
    }

    @Test
    fun fullWhilePluggedCountsAsCharging() {
        assertTrue(DeviceHealth.fromBatteryExtras(100, 100, status = 5, plugged = 2, temperatureTenths = 300, thermalStatus = 0).charging)
    }

    @Test
    fun notificationKeyIgnoresTenthsButFollowsWholeDegreesAndWarnings() {
        val base = DeviceHealth(56, charging = true, temperatureC = 36.6, thermalStatus = 0)
        assertEquals(base.notificationKey, base.copy(temperatureC = 36.9).notificationKey)
        assertTrue(base.notificationKey != base.copy(temperatureC = 37.6).notificationKey)
        assertTrue(base.notificationKey != base.copy(thermalStatus = 2).notificationKey)
        assertTrue(base.notificationKey != base.copy(batteryPct = 55).notificationKey)
    }
}
