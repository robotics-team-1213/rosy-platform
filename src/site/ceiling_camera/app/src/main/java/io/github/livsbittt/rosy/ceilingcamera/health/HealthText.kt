package io.github.livsbittt.rosy.overhead.health

import android.content.res.Resources
import io.github.livsbittt.rosy.overhead.R
import java.util.Locale

/** Korean health text shared by the stream screen and the foreground notification. */
object HealthText {
    /** "배터리 56% · 충전 중 · 36.6 °C"; parts that are unknown are left out. */
    fun line(res: Resources, h: DeviceHealth): String = buildList {
        h.batteryPct?.let { add(res.getString(R.string.health_battery, it)) }
        add(res.getString(if (h.charging) R.string.health_charging else R.string.health_on_battery))
        h.temperatureC?.let { add(res.getString(R.string.health_temperature, String.format(Locale.ROOT, "%.1f", it))) }
    }.joinToString(" · ")

    fun warning(res: Resources, w: HealthWarning, h: DeviceHealth): String = when (w) {
        HealthWarning.HOT -> res.getString(R.string.health_hot)
        HealthWarning.BATTERY_LOW -> res.getString(R.string.health_battery_low, h.batteryPct ?: 0)
    }
}
