package io.github.livsbittt.rosy.cam.settings

import io.github.livsbittt.rosy.cam.link.certPin
import java.io.ByteArrayInputStream
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.format.ResolverStyle
import java.util.Base64

/**
 * The shared D-391 1 site-link record (`site_name`, `tls_host`, `port`, `ca_pem`, `role`, `credential_id`,
 * `expires_at`, exactly one of `credential`/`credential_ref`, optional `manual_host`), as one JSON object read
 * into a map. Machine source: `test/fixtures/protocol/site-link.v1.json`; same rules and check order as
 * core_common `site_link.py`. Pure JVM.
 *
 * The app does not store this shape: [SiteLink] keeps a CA pin instead of `ca_pem` and the token itself instead
 * of `credential`/`credential_ref` (see [toSiteLink]). This is the validator for a record received from the
 * site (the D-391 4항 4단계 pairing client) before it becomes a [SiteLink].
 */
object SiteLinkRecord {
    val REASONS = listOf(
        "missing_field", "bad_value", "ip_as_tls_host", "bad_tls_host", "bad_ca_pem", "leaf_not_ca",
        "bad_port", "unknown_role", "bad_expires_at", "missing_credential", "credential_conflict",
        "bad_manual_host",
    )

    /** D-391 client roles (core_common device_kind.ALL). */
    val ROLES = listOf(SiteLink.ROLE, "robot")

    private val REQUIRED = listOf("site_name", "tls_host", "port", "ca_pem", "role", "credential_id", "expires_at")
    private val TLS_HOST = Regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.local$")
    private val DNS_NAME = Regex(
        "^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$",
    )
    private val EXPIRES_AT = Regex("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d{1,9})?Z$")
    private val EXPIRES_AT_SECONDS = DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss").withResolverStyle(ResolverStyle.STRICT)
    private val PEM_BLOCK = Regex("-----BEGIN CERTIFICATE-----([A-Za-z0-9+/=\\s]*?)-----END CERTIFICATE-----")

    /** Null for a usable record, else one reason from [REASONS]. Unknown top-level fields are ignored. */
    fun validate(record: Map<String, Any?>): String? {
        if (REQUIRED.any { record[it] == null }) return "missing_field"
        for (name in listOf("site_name", "credential_id")) {
            val value = record[name]
            if (value !is String || value.isBlank()) return "bad_value"
        }

        val tlsHost = record["tls_host"] as? String ?: return "bad_tls_host"
        if (SiteLink.isIpLiteral(tlsHost)) return "ip_as_tls_host"
        if (!TLS_HOST.matches(tlsHost.lowercase())) return "bad_tls_host"

        // JSON booleans and strings are not ports; whole numbers only.
        val port = record["port"]
        if (port !is Int || port !in 1..65535) return "bad_port"
        if (record["role"] !in ROLES) return "unknown_role"
        if (!isUtcTimestamp(record["expires_at"])) return "bad_expires_at"

        caPemReason(record["ca_pem"])?.let { return it }

        val inline = record["credential"] != null
        val hasRef = record["credential_ref"] != null
        if (inline && hasRef) return "credential_conflict"
        if (!inline && !hasRef) return "missing_credential"
        val credential = if (inline) record["credential"] else record["credential_ref"]
        if (credential !is String || credential.isEmpty()) return "bad_value"

        val manualHost = record["manual_host"]
        if (manualHost != null && !(manualHost is String && (SiteLink.isIpLiteral(manualHost) || DNS_NAME.matches(manualHost)))) {
            return "bad_manual_host"
        }
        return null
    }

    /** The CA certificates of [pem]: every PEM block parsed, nothing else in the text. Null when any part is bad. */
    fun caCertificates(pem: Any?): List<X509Certificate>? {
        if (pem !is String) return null
        val blocks = PEM_BLOCK.findAll(pem).toList()
        if (blocks.isEmpty() || PEM_BLOCK.replace(pem, "").isNotBlank()) return null
        val factory = CertificateFactory.getInstance("X.509")
        return blocks.map { block ->
            try {
                val der = Base64.getDecoder().decode(block.groupValues[1].filterNot { it.isWhitespace() })
                factory.generateCertificate(ByteArrayInputStream(der)) as X509Certificate
            } catch (e: IllegalArgumentException) {
                return null
            } catch (e: CertificateException) {
                return null
            }
        }
    }

    /** `bad_ca_pem` unless every block parses; `leaf_not_ca` if any block is not a CA (basicConstraints cA). */
    private fun caPemReason(pem: Any?): String? {
        val certs = caCertificates(pem) ?: return "bad_ca_pem"
        return if (certs.all { it.basicConstraints >= 0 }) null else "leaf_not_ca"
    }

    private fun isUtcTimestamp(value: Any?): Boolean {
        if (value !is String || !EXPIRES_AT.matches(value)) return false
        return try {
            LocalDateTime.parse(value.substring(0, 19), EXPIRES_AT_SECONDS)
            true
        } catch (e: DateTimeParseException) {
            false
        }
    }

    /**
     * A valid shared [record] as the app's stored [SiteLink], given the camera [token] (the inline `credential`,
     * or the secret behind `credential_ref`) and its `source` name. Null for an invalid record, or a valid one
     * for another role (a `robot` record is FleetAgent's, not this app's).
     *
     * Field mapping: `ca_pem` becomes the pin of its first CA certificate (the D-341 9 pin the link trusts);
     * `tls_host` is lower-cased; an IP `manual_host` is kept, a host-name `manual_host` is dropped because the
     * app dials the manual address without DNS (D-391 1 fallback, review M1).
     */
    fun toSiteLink(record: Map<String, Any?>, token: String, source: String): SiteLink? {
        if (validate(record) != null || record["role"] != SiteLink.ROLE) return null
        val ca = caCertificates(record["ca_pem"])?.firstOrNull() ?: return null
        val manual = (record["manual_host"] as? String)?.takeIf { SiteLink.isIpLiteral(it) }
        return SiteLink(
            siteName = record["site_name"] as String,
            tlsHost = (record["tls_host"] as String).lowercase(),
            port = record["port"] as Int,
            caPin = certPin(ca.encoded),
            token = token,
            source = source,
            secure = true,
            manualHost = manual,
            role = record["role"] as String,
            expiresAt = record["expires_at"] as String,
        )
    }
}
