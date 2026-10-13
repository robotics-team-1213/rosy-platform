package io.github.livsbittt.rosy.cam.settings

import android.content.Context
import android.net.ConnectivityManager
import io.github.livsbittt.rosy.cam.ui.currentLan

/** Short-lived settings lookup, sharing API-34 callbacks and sequential legacy resolution with reconnects. */
class OverheadServerDiscovery(
    context: Context,
    private val onRecords: (List<OverheadServiceRecord>, List<RobotCoreServiceRecord>, Boolean, Boolean) -> Unit,
) {
    private val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private val overhead = linkedMapOf<String, OverheadServiceRecord>()
    private val cores = linkedMapOf<String, RobotCoreServiceRecord>()
    private var wifiConnected = false
    private var started = false
    private var stopped = false
    private val session = NsdDiscoverySession(context,
        listOf(OverheadServiceRecord.SERVICE_TYPE, RobotCoreServiceRecord.SERVICE_TYPE),
        onRecord = { info, _ ->
            if (!stopped) {
                when (normalizeServiceType(info.serviceType)) {
                    normalizeServiceType(OverheadServiceRecord.SERVICE_TYPE) -> OverheadServiceRecord.parse(info)?.let { overhead[it.name] = it }
                    normalizeServiceType(RobotCoreServiceRecord.SERVICE_TYPE) -> RobotCoreServiceRecord.parse(info)?.let { cores[it.name] = it }
                }
                publish(true)
            }
        },
        onLost = { type, name ->
            if (!stopped) {
                if (type == normalizeServiceType(OverheadServiceRecord.SERVICE_TYPE)) overhead.remove(name) else cores.remove(name)
                publish(true)
            }
        },
        onFinished = { if (!stopped) { publish(false); stopped = true } },
    )
    fun start() {
        if (stopped || started) return
        started = true
        wifiConnected = connectivity.currentLan() != null
        publish(wifiConnected)
        if (wifiConnected) session.start(18_000) else stopped = true
    }
    fun stop() { stopped = true; session.stop() }
    private fun publish(scanning: Boolean) = onRecords(overhead.values.toList(), cores.values.toList(), scanning, wifiConnected)
}
