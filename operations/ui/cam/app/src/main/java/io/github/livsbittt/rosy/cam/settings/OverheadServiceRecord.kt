package io.github.livsbittt.rosy.cam.settings

import android.net.nsd.NsdServiceInfo
import io.github.livsbittt.rosy.cam.pairing.Pairing
import java.nio.charset.StandardCharsets

/**
 * Public, non-secret mDNS data for the camera's Rosy Vision receiver. [address] is the resolved IP (dialled for
 * a pairing request only, with SNI [tlsHost]); [pairable] is the D-341 14 rule (TXT `pair=rosy-pair/1`).
 */
data class OverheadServiceRecord(
    val serviceName: String,
    val tlsHost: String,
    val port: Int,
    val address: String? = null,
    val pairable: Boolean = false,
    val peerApproval: Boolean = false,
) {
    val name: String get() = serviceName
    companion object {
        const val SERVICE_TYPE = "_rosy-overhead._tcp."
        private val SINGLE_LABEL_LOCAL = Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.local")

        fun parse(info: NsdServiceInfo): OverheadServiceRecord? {
            val txt = info.attributes.mapValues { (_, value) -> value?.toString(StandardCharsets.UTF_8)?.toByteArray(StandardCharsets.UTF_8) }
            val record = parse(info.serviceType, info.serviceName, info.port, txt) ?: return null
            @Suppress("DEPRECATION")
            val address = dialAddress(info.host?.hostAddress)
            return record.copy(
                address = address,
                pairable = Pairing.pairable(info.serviceType, null, address, info.port, txt) == null,
                peerApproval = record.peerApproval && address != null,
            )
        }

        fun parse(serviceType: String, serviceName: String, tlsHost: String, port: Int, attributes: Map<String, ByteArray?>): OverheadServiceRecord? {
            if (rejection(serviceType, tlsHost, port, attributes) != null) return null
            return OverheadServiceRecord(serviceName, normalizeHost(attributes.text("tls_host").orEmpty()), port,
                peerApproval = attributes.text("peer") == "rosy.camera-peer/1")
        }

        /**
         * The NSD address as a pairing dial target: a plain IPv4/IPv6 literal only. A scoped link-local address
         * (`fe80::1%wlan0`) or anything else is no target, so the record gets no "연결 요청" button.
         */
        internal fun dialAddress(hostAddress: String?): String? = hostAddress?.takeIf { SiteLink.isIpLiteral(it) }

        private fun parse(serviceType: String, serviceName: String, port: Int, attributes: Map<String, ByteArray?>): OverheadServiceRecord? {
            if (rejection(serviceType, null, port, attributes) != null) return null
            return OverheadServiceRecord(serviceName, normalizeHost(attributes.text("tls_host").orEmpty()), port,
                peerApproval = attributes.text("peer") == "rosy.camera-peer/1")
        }

        /**
         * Rejection reason in the D-370 discovery vocabulary, or null when accepted
         * (test/fixtures/protocol/discovery-txt.v1.json). [resolvedHost] is null when unknown.
         */
        internal fun rejection(serviceType: String, resolvedHost: String?, port: Int, attributes: Map<String, ByteArray?>): String? {
            if (normalizeServiceType(serviceType) != normalizeServiceType(SERVICE_TYPE)) return "wrong_type"
            if (port !in 1..65535) return "bad_port"
            val txt = attributes.mapValues { (_, value) -> value?.toString(StandardCharsets.UTF_8)?.trim().orEmpty() }
            commonKeyRejection(txt, "overhead-camera", "rosy-overhead/1", "required")?.let { return it }
            if ("peer" in txt && (txt["peer"] != "rosy.camera-peer/1" || txt["pair"] != "rosy-pair/1")) return "value_mismatch"
            val tlsHost = attributes.text("tls_host") ?: return "missing_key"
            // Same rule as core_common discovery_txt: one label + ".local", compared case-insensitively
            // with a trailing root dot trimmed.
            if (!normalizeHost(tlsHost).matches(SINGLE_LABEL_LOCAL)) return "bad_host"
            if (resolvedHost != null && normalizeHost(resolvedHost) != normalizeHost(tlsHost)) return "tls_host_mismatch"
            return null
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
            val address = resolvedHost?.takeIf { SiteLink.isIpLiteral(it) }
            val hostname = resolvedHost?.takeUnless { SiteLink.isIpLiteral(it) }
            if (rejection(serviceType, address, port, attributes, hostname) != null) return null
            return RobotCoreServiceRecord(serviceName, resolvedHost ?: return null, port)
        }

        /** Rejection reason in the D-370 discovery vocabulary, or null when accepted. */
        internal fun rejection(serviceType: String, resolvedHost: String?, port: Int, attributes: Map<String, ByteArray?>, hostname: String? = null): String? {
            if (normalizeServiceType(serviceType) != normalizeServiceType(SERVICE_TYPE)) return "wrong_type"
            if (hostname != null && !SiteLink.isTlsHost(SiteLink.normalizeHost(hostname))) return "bad_host"
            if (resolvedHost != null && !lanIpv4(resolvedHost)) return "bad_address"
            if (port !in 1..65535) return "bad_port"
            val txt = attributes.mapValues { (_, value) -> value?.toString(StandardCharsets.UTF_8)?.trim().orEmpty() }
            val legacy = listOf("product", "role", "proto", "tls").none { it in txt }
            if (!legacy) commonKeyRejection(txt, "robot", "core-v1", txt["tls"]?.takeIf { it in listOf("none", "required") } ?: "none")?.let { return it }
            return if (txt["network"] == "ap") "ap_mode" else null
        }

        private fun lanIpv4(address: String): Boolean {
            if (!SiteLink.isIpLiteral(address) || address.contains(':')) return false
            val octets = address.split('.').map { it.toInt() }
            // Match Python ipaddress.is_private, including documentation/benchmark ranges used in vectors.
            return (octets[0] == 0 && octets.any { it != 0 }) || octets[0] == 10 ||
                (octets[0] == 172 && octets[1] in 16..31) ||
                (octets[0] == 192 && octets[1] == 168) ||
                (octets[0] == 192 && octets[1] == 0 && octets[2] == 0 && octets[3] !in listOf(9, 10)) ||
                (octets[0] == 192 && octets[1] == 0 && octets[2] == 2) ||
                (octets[0] == 198 && octets[1] in 18..19) ||
                (octets[0] == 198 && octets[1] == 51 && octets[2] == 100) ||
                (octets[0] == 203 && octets[1] == 0 && octets[2] == 113) || octets[0] >= 240
        }
    }
}

/** product/role/proto/tls check shared by both records: missing_key before value_mismatch, in key order. */
private fun commonKeyRejection(txt: Map<String, String>, role: String, proto: String, tls: String): String? {
    for ((key, expected) in listOf("product" to "rosy", "role" to role, "proto" to proto, "tls" to tls)) {
        val value = txt[key] ?: return "missing_key"
        if (value != expected) return "value_mismatch"
    }
    return null
}

private fun Map<String, ByteArray?>.text(key: String): String? = this[key]?.toString(StandardCharsets.UTF_8)?.trim()

internal fun normalizeServiceType(serviceType: String): String = serviceType
    .trim()
    .trimEnd('.')
    .removeSuffix(".local")
    .trimEnd('.')
    .removePrefix(".")
    .lowercase()

private fun normalizeHost(host: String): String = host.trim().lowercase().trimEnd('.')
