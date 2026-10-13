package io.github.livsbittt.rosy.cam.health

/**
 * One heat line for the ceiling phone (D-691).
 *
 * Severe heat is PowerManager.THERMAL_STATUS_SEVERE or worse, or a battery at
 * 45°C when the OS reports no thermal status. That is the same line that turns
 * the screen off. Below it, the light can already be held at 43°C. Cooling is
 * THERMAL_STATUS_LIGHT or better, or 41°C, so a pause does not flap.
 */
internal object PhoneHeat {
    const val SEVERE = 3
    const val LIGHT = 1
    const val PAUSE_BATTERY_C = 45.0
    const val RELEASE_BATTERY_C = 41.0

    fun severe(health: DeviceHealth): Boolean {
        val thermal = health.thermalStatus
        return if (thermal != DeviceHealth.THERMAL_UNKNOWN) thermal >= SEVERE
        else health.temperatureC?.let { it >= PAUSE_BATTERY_C } ?: false
    }

    fun cooled(health: DeviceHealth): Boolean {
        val thermal = health.thermalStatus
        return if (thermal != DeviceHealth.THERMAL_UNKNOWN) thermal <= LIGHT
        else health.temperatureC?.let { it <= RELEASE_BATTERY_C } ?: false
    }
}
