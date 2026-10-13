package io.github.livsbittt.rosy.cam.health

/**
 * Stops the ceiling sensor and JPEG while the phone is severely hot (D-691).
 * A Rosy request does not override this. The socket stays up. The pause holds
 * until [PhoneHeat.cooled], including across a missing health sample.
 */
class CaptureCoolingPolicy {
    private var paused = false

    fun paused(health: DeviceHealth?): Boolean {
        if (health == null) return paused
        if (PhoneHeat.cooled(health)) paused = false
        if (PhoneHeat.severe(health)) paused = true
        return paused
    }
}
