package io.github.livsbittt.rosy.cam.settings

import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneOffset
import org.json.JSONObject

/** D-432 approval scope. Discovery is never authentication; TLS and camera credentials remain required. */
data class LinkPolicy(
    val mode: String = "paired",
    val siteName: String = "",
    val expiresAt: Instant = Instant.EPOCH,
    val devices: List<DeviceBinding> = emptyList(),
) {
    data class DeviceBinding(val deviceId: String, val serviceType: String, val tlsHost: String)

    fun permits(deviceId: String, serviceType: String, tlsHost: String, authenticated: Boolean, now: Instant = Instant.now()): Boolean =
        mode == "development" && authenticated && now < expiresAt && DeviceBinding(deviceId, serviceType, tlsHost) in devices

    companion object {
        private val TYPES = setOf("_rosy._tcp", "_rosy-fleet._tcp", "_rosy-overhead._tcp", "_rosy-dock._tcp", "_rosy-signal._tcp")

        fun parse(data: JSONObject?, production: Boolean = false, now: Instant = Instant.now()): LinkPolicy {
            if (data == null) return LinkPolicy()
            val mode = data.opt("mode")
            require(mode == "paired" || mode == "development") { "invalid link mode" }
            if (mode == "paired") {
                require(data.keys().asSequence().toSet() == setOf("mode")) { "paired policy cannot carry development scope" }
                return LinkPolicy()
            }
            require(!production) { "production cannot enable development link mode" }
            require(data.keys().asSequence().toSet() == setOf("mode", "site_name", "expires_at", "devices")) { "invalid development scope" }
            val site = data.opt("site_name") as? String
            require(!site.isNullOrBlank()) { "invalid development site name" }
            val timestamp = data.opt("expires_at") as? String ?: error("invalid development expiry")
            val parsed = OffsetDateTime.parse(timestamp)
            require(parsed.offset == ZoneOffset.UTC && parsed.year >= 1) { "development expiry must be UTC" }
            val expiry = parsed.toInstant()
            require(expiry > now) { "development policy has expired" }
            val rows = data.getJSONArray("devices")
            require(rows.length() in 1..64) { "development policy requires 1..64 devices" }
            val devices = ArrayList<DeviceBinding>()
            for (i in 0 until rows.length()) {
                val row = rows.getJSONObject(i)
                require(row.keys().asSequence().toSet() == setOf("device_id", "service_type", "tls_host")) { "invalid device binding" }
                val id = row.opt("device_id") as? String
                val type = row.opt("service_type") as? String
                val host = row.opt("tls_host") as? String
                require(!id.isNullOrBlank() && id.length <= 96 && type in TYPES && host != null && SiteLink.isTlsHost(host)) { "invalid device binding" }
                val binding = DeviceBinding(id, type!!, host)
                require(devices.none { (it.deviceId == id && it.serviceType == type) || (it.serviceType == type && it.tlsHost == host) }) { "duplicate development device binding" }
                devices += binding
            }
            return LinkPolicy("development", site, expiry, devices)
        }
    }
}

/** Trusted local bootstrap exported by the site tool; imports a CA pin rather than trusting an mDNS advert. */
data class DevelopmentBootstrap(val policy: LinkPolicy, val link: SiteLink, val policyJson: String) {
    companion object {
        const val MAX_BYTES = 65536
        fun parse(text: String, now: Instant = Instant.now()): DevelopmentBootstrap {
            require(text.toByteArray(Charsets.UTF_8).size <= MAX_BYTES) { "bootstrap too large" }
            val envelope = JSONObject(text)
            require(envelope.keys().asSequence().toSet() == setOf("policy", "site_link", "source")) { "invalid bootstrap envelope" }
            val policyObject = envelope.getJSONObject("policy")
            val policy = LinkPolicy.parse(policyObject, now = now)
            require(policy.mode == "development") { "development policy required" }
            val record = envelope.getJSONObject("site_link").let { json -> json.keys().asSequence().toSet().associateWith { key -> json.opt(key).takeUnless { it == JSONObject.NULL } } }
            val token = record["credential"] as? String ?: error("inline camera credential required")
            val source = envelope.getString("source")
            val link = SiteLinkRecord.toSiteLink(record, token, source) ?: error("invalid camera site link")
            require(SiteLink.validate(link) == null && link.siteName == policy.siteName) { "site mismatch" }
            require(Instant.parse(link.expiresAt) > now && Instant.parse(link.expiresAt) <= policy.expiresAt) { "invalid credential expiry" }
            require(policy.permits(source, "_rosy-overhead._tcp", link.tlsHost!!, authenticated = true, now = now)) { "camera outside development scope" }
            require(link.manualHost == null) { "development bootstrap requires discovery" }
            return DevelopmentBootstrap(policy, link, policyObject.toString())
        }
    }
}
