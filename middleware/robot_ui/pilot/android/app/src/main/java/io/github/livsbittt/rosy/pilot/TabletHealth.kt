package io.github.livsbittt.rosy.pilot

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import io.github.livsbittt.rosy.cam.health.DeviceHealth

/** Android sensor adapter; the shared Cam policy owns thermal thresholds and hysteresis. */
class TabletHealth(private val context: Context, private val changed: (DeviceHealth) -> Unit) {
    private val power = context.getSystemService(Context.POWER_SERVICE) as PowerManager
    private var active = false
    private var battery: Intent? = null
    private var thermal = DeviceHealth.THERMAL_UNKNOWN
    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) { battery = intent; emit() }
    }
    private val thermalListener by lazy { PowerManager.OnThermalStatusChangedListener { value -> thermal = value; emit() } }
    fun start() {
        if (active) return
        active = true
        if (Build.VERSION.SDK_INT >= 29) {
            thermal = power.currentThermalStatus
            power.addThermalStatusListener(context.mainExecutor, thermalListener)
        }
        battery = context.registerReceiver(receiver, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        emit()
    }
    fun stop() {
        if (!active) return
        active = false
        context.unregisterReceiver(receiver)
        if (Build.VERSION.SDK_INT >= 29) power.removeThermalStatusListener(thermalListener)
    }
    private fun emit() {
        if (!active) return
        val data = battery
        changed(DeviceHealth.fromBatteryExtras(
            data?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1,
            data?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1,
            data?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1,
            data?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0,
            data?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, DeviceHealth.NO_TEMPERATURE) ?: DeviceHealth.NO_TEMPERATURE,
            thermal))
    }
}
