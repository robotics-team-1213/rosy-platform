package io.github.livsbittt.rosy.cam.health

/** Screen heat protection is local to the app device, never a robot motion policy. */
class ScreenCoolingPolicy {
    private var latched = false
    fun requestSleep(health: DeviceHealth?): Boolean {
        if (health == null) return false
        val thermal = health.thermalStatus
        val hot = if (thermal != DeviceHealth.THERMAL_UNKNOWN) thermal >= 3
            else health.temperatureC?.let { it >= 45.0 } ?: false
        val cool = if (thermal != DeviceHealth.THERMAL_UNKNOWN) thermal <= 1
            else health.temperatureC?.let { it <= 41.0 } ?: false
        if (cool) latched = false
        if (!hot || latched) return false
        latched = true
        return true
    }
}
