package io.github.livsbittt.rosy.cam.health

/** Screen heat protection is local to the app device, never a robot motion policy. */
class ScreenCoolingPolicy {
    private var latched = false
    val coolingRequired: Boolean get() = latched
    fun requestSleep(health: DeviceHealth?): Boolean {
        if (health == null) return false
        if (PhoneHeat.cooled(health)) latched = false
        if (!PhoneHeat.severe(health) || latched) return false
        latched = true
        return true
    }
}
