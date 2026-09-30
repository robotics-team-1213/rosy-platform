package io.github.livsbittt.rosy.overhead.health

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Follows the sticky ACTION_BATTERY_CHANGED broadcast and, on API 29+, the thermal status
 * listener. Local to the phone: nothing here goes on the wire (rosy-overhead/1 has no client
 * status message). Main thread only.
 */
class DeviceHealthMonitor(private val context: Context) {
    private val _health = MutableStateFlow<DeviceHealth?>(null)
    val health: StateFlow<DeviceHealth?> = _health.asStateFlow()

    private val power = context.getSystemService(Context.POWER_SERVICE) as PowerManager
    private var lastBattery: Intent? = null
    private var thermalListener: PowerManager.OnThermalStatusChangedListener? = null

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            lastBattery = intent
            publish()
        }
    }

    fun start() {
        // A sticky broadcast: registering returns the current value at once.
        ContextCompat.registerReceiver(
            context,
            receiver,
            IntentFilter(Intent.ACTION_BATTERY_CHANGED),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )?.let { lastBattery = it }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val listener = PowerManager.OnThermalStatusChangedListener { publish() }
            power.addThermalStatusListener(ContextCompat.getMainExecutor(context), listener)
            thermalListener = listener
        }
        publish()
    }

    fun stop() {
        runCatching { context.unregisterReceiver(receiver) }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            thermalListener?.let { power.removeThermalStatusListener(it) }
        }
        thermalListener = null
    }

    private fun publish() {
        val battery = lastBattery ?: return
        val thermal = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            power.currentThermalStatus
        } else {
            DeviceHealth.THERMAL_UNKNOWN
        }
        _health.value = DeviceHealth.fromBatteryExtras(
            level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1),
            scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1),
            status = battery.getIntExtra(BatteryManager.EXTRA_STATUS, -1),
            plugged = battery.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0),
            temperatureTenths = battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, DeviceHealth.NO_TEMPERATURE),
            thermalStatus = thermal,
        )
    }
}
