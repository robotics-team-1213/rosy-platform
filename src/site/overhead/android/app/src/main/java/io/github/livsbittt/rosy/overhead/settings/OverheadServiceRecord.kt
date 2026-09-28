package io.github.livsbittt.rosy.overhead.settings

import android.net.nsd.NsdServiceInfo
import java.nio.charset.StandardCharsets

/** Public, non-secret mDNS data for the camera's Site Vision receiver. */
data class OverheadServiceRecord(val serviceName: String, val tlsHost: String, val port: Int) {
    val name: String get() = serviceName
    companion object {
        const val SERVICE_TYPE = "_rosy-overhead._tcp."

        fun parse(info: NsdServiceInfo): OverheadServiceRecord? {
            val txt = info.attributes.mapValues { (_, value) -> value?.toString(StandardCharsets.UTF_8)?.toByteArray(StandardCharsets.UTF_8) }
            return parse(info.serviceType, info.serviceName, info.port, txt)
        }

        fun parse(serviceType: String, serviceName: String, tlsHost: String, port: Int, attributes: Map<String, ByteArray?>): OverheadServiceRecord? {
            if (tlsHost != attributes.text("tls_host")) return null
            return parse(serviceType, serviceName, port, attributes)
        }

        private fun parse(serviceType: String, serviceName: String, port: Int, attributes: Map<String, ByteArray?>): OverheadServiceRecord? {
            if (normalizeServiceType(serviceType) != normalizeServiceType(SERVICE_TYPE)) return null
            val txt = attributes.mapValues { (_, value) -> value?.toString(StandardCharsets.UTF_8)?.trim().orEmpty() }
            if (txt["product"] != "rosy" || txt["role"] != "overhead-camera" ||
                txt["proto"] != "rosy-overhead/1" || txt["tls"] != "required"
            ) return null
            val host = txt["tls_host"].orEmpty().lowercase()
            if (!host.matches(Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\\.local"))) return null
            if (port !in 1..65535) return null
            return OverheadServiceRecord(serviceName, host, port)
        }
    }
}

/** Robot CORE discovery is informational and must never be used as the camera frame target. */
data class RobotCoreServiceRecord(val name: String, val host: String, val port: Int) {
    companion object {
        const val SERVICE_TYPE = "_rosy._tcp."

        fun parse(info: NsdServiceInfo): RobotCoreServiceRecord? {
            val txt = info.attributes.mapValues { (_, value) -> value?.toString(StandardCharsets.UTF_8)?.toByteArray(StandardCharsets.UTF_8) }
            return parse(info.serviceType, info.serviceName, info.host?.hostAddress, info.port, txt)
        }

        fun parse(serviceType: String, serviceName: String, resolvedHost: String?, port: Int, attributes: Map<String, ByteArray?>): RobotCoreServiceRecord? {
            if (normalizeServiceType(serviceType) != normalizeServiceType(SERVICE_TYPE)) return null
            val txt = attributes.mapValues { (_, value) -> value?.toString(StandardCharsets.UTF_8)?.trim().orEmpty() }
            if (txt["product"] != "rosy" || txt["role"] != "robot" ||
                txt["proto"] != "core-v1" || txt["tls"] != "none"
            ) return null
            val host = resolvedHost ?: return null
            if (port !in 1..65535) return null
            return RobotCoreServiceRecord(serviceName, host, port)
        }
    }
}

private fun Map<String, ByteArray?>.text(key: String): String? = this[key]?.toString(StandardCharsets.UTF_8)?.trim()

internal fun normalizeServiceType(serviceType: String): String = serviceType
    .trim()
    .trimEnd('.')
    .removeSuffix(".local")
    .trimEnd('.')
    .removePrefix(".")
    .lowercase()
