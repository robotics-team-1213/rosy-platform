package io.github.livsbittt.rosy.ceilingcamera.health

/** Health condition that needs the operator; nominal health has no warning (D-82). */
enum class HealthWarning { HOT, BATTERY_LOW }

/**
 * Battery and thermal facts of the phone. Pure JVM so the thresholds are unit-tested; the
 * Android side ([DeviceHealthMonitor]) fills it from ACTION_BATTERY_CHANGED and PowerManager.
 *
 * @property thermalStatus PowerManager.THERMAL_STATUS_* value, or [THERMAL_UNKNOWN] before API 29.
 */
data class DeviceHealth(
    val batteryPct: Int?,
    val charging: Boolean,
    val temperatureC: Double?,
    val thermalStatus: Int = THERMAL_UNKNOWN,
) {
    val warnings: List<HealthWarning>
        get() = buildList {
            val hot = if (thermalStatus != THERMAL_UNKNOWN) {
                thermalStatus >= THERMAL_MODERATE
            } else {
                (temperatureC ?: 0.0) >= HOT_BATTERY_C
            }
            if (hot) add(HealthWarning.HOT)
            if (batteryPct != null && batteryPct < LOW_BATTERY_PCT && !charging) add(HealthWarning.BATTERY_LOW)
        }

    /** What the notification is refreshed on: whole degrees C, battery, charging and warnings. */
    val notificationKey: List<Any?>
        get() = listOf(batteryPct, charging, temperatureC?.let { Math.round(it) }, warnings)

    companion object {
        const val THERMAL_UNKNOWN = -1

        /** Default for a missing EXTRA_TEMPERATURE. */
        const val NO_TEMPERATURE = Int.MIN_VALUE

        /** PowerManager.THERMAL_STATUS_MODERATE. */
        const val THERMAL_MODERATE = 2
        const val LOW_BATTERY_PCT = 20

        /** Fallback before API 29 when there is no thermal status: battery temperature in °C. */
        const val HOT_BATTERY_C = 43.0

        /** BatteryManager.BATTERY_STATUS_CHARGING / _FULL. */
        private const val STATUS_CHARGING = 2
        private const val STATUS_FULL = 5

        /**
         * Parses the ACTION_BATTERY_CHANGED extras: level/scale, status or plugged,
         * temperature in tenths of °C. A missing level (-1) or temperature ([NO_TEMPERATURE]) becomes null.
         */
        fun fromBatteryExtras(level: Int, scale: Int, status: Int, plugged: Int, temperatureTenths: Int, thermalStatus: Int): DeviceHealth {
            val pct = if (level >= 0 && scale > 0) (level * 100 + scale / 2) / scale else null
            val charging = status == STATUS_CHARGING || status == STATUS_FULL || plugged > 0
            val temp = if (temperatureTenths != NO_TEMPERATURE) temperatureTenths / 10.0 else null
            return DeviceHealth(pct, charging, temp, thermalStatus)
        }
    }
}
