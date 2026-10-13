package io.github.livsbittt.rosy.cam.settings

import android.content.Context
import io.github.livsbittt.rosy.cam.link.SiteBrowser
import io.github.livsbittt.rosy.cam.link.SiteSighting
import java.net.Inet4Address

/** Reconnect browse uses the same bounded resolver and cancellation rules as the settings scan. */
class NsdSiteBrowser(private val context: Context) : SiteBrowser {
    override fun browse(timeoutMs: Long, match: (SiteSighting) -> Boolean): List<SiteSighting> {
        val guard = Any()
        val sightings = linkedMapOf<String, SiteSighting>()
        var firstMatchAt: Long? = null
        val session = NsdDiscoverySession(context, listOf(OverheadServiceRecord.SERVICE_TYPE),
            onRecord = { info, addresses ->
                val parsed = OverheadServiceRecord.parse(info)
                if (parsed != null && addresses.isNotEmpty()) synchronized(guard) {
                    val sighting = SiteSighting(parsed.serviceName, parsed.tlsHost, parsed.port,
                        addresses.take(8).sortedBy { if (it is Inet4Address) 0 else 1 })
                    sightings[sighting.serviceName] = sighting
                    if (firstMatchAt == null && match(sighting)) firstMatchAt = now()
                }
            },
            onLost = { _, name -> synchronized(guard) { sightings.remove(name) } },
        )
        try {
            session.start(timeoutMs)
            var end = now() + timeoutMs.coerceIn(1, 18_000)
            while (now() < end) {
                synchronized(guard) { firstMatchAt }?.let { end = minOf(end, it + 400) }
                Thread.sleep(50)
            }
            return synchronized(guard) { sightings.values.filter(match) }
        } finally { session.stop() }
    }
    private fun now(): Long = System.nanoTime() / 1_000_000
}
