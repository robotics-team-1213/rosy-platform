package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.settings.OverheadServiceRecord
import io.github.livsbittt.rosy.cam.settings.RobotCoreServiceRecord
import io.github.livsbittt.rosy.cam.settings.SiteLink
import io.github.livsbittt.rosy.cam.settings.normalizeServiceType
import java.nio.ByteBuffer
import java.nio.charset.StandardCharsets.UTF_8
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.Locale

/**
 * `rosy-pair/1` pure logic (D-341 3, 4, 14): the confirmation code, the client commit, the site CA fingerprint
 * and the pairable-record rule. Port of core_common `protocol/pairing.py`; machine source
 * `test/fixtures/protocol/pairing.v1.json`. Pure JVM.
 *
 * Code input: six UTF-8 fields, each prefixed by its byte length as a 4-byte big-endian unsigned integer, in the
 * order [PROTO], role, request_id, leaf_cert_sha256 (lowercase hex text), client_nonce, server_nonce.
 * `decimal6` = the first 8 digest bytes as a big-endian **unsigned** integer mod 1,000,000, zero-padded.
 */
object Pairing {
    const val PROTO = "rosy-pair/1"
    const val ROLE = SiteLink.ROLE
    const val MAX_REQUEST_BYTES = 4096

    val REQUEST_REASONS = listOf("too_large", "not_object", "unknown_field", "missing_field", "proto", "role", "bad_value")
    val RESULT_REASONS = listOf(
        "not_object", "missing_field", "proto", "role", "bad_value", "bad_tls_host", "bad_ca_pem", "leaf_not_ca",
        "bad_expires_at",
    )

    /** Reasons [pairable] adds on top of the D-370 discovery reasons. */
    val PAIRABLE_REASONS_ADDED = listOf("not_overhead", "no_pair")

    /** 32 random bytes as base64url without padding: nonces, the poll secret and the token. */
    val SECRET_PATTERN = Regex("^[A-Za-z0-9_-]{43}$")
    val SHA256_HEX = Regex("^[0-9a-f]{64}$")
    val CODE_PATTERN = Regex("^[0-9]{6}$")

    private val FINGERPRINT_INPUT = Regex("^[0-9A-Fa-f]{64}$")
    private val FIRST_PEM = Regex("-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", RegexOption.DOT_MATCHES_ALL)
    private val random = SecureRandom()

    /** A fresh secret: 32 random bytes, base64url without padding (43 characters). */
    fun newSecret(): String {
        val bytes = ByteArray(32).also(random::nextBytes)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    }

    /** Lowercase hex SHA-256 of [value]'s UTF-8 bytes (commit and poll-secret digests). */
    fun sha256Text(value: String): String = hex(sha256(value.toByteArray(UTF_8)))

    /** `client_commit`, sent before the nonce is revealed. */
    fun commit(clientNonce: String): String = sha256Text(clientNonce)

    /** The six-digit code both sides compute; a relayed TLS leaf changes it (D-341 3). */
    fun confirmationCode(
        role: String,
        requestId: String,
        leafCertSha256: String,
        clientNonce: String,
        serverNonce: String,
    ): String {
        val parts = listOf(PROTO, role, requestId, leafCertSha256, clientNonce, serverNonce).map { it.toByteArray(UTF_8) }
        val framed = ByteBuffer.allocate(parts.sumOf { 4 + it.size })
        for (part in parts) framed.putInt(part.size).put(part)
        val digest = sha256(framed.array())
        // ByteBuffer.getLong is signed; Long.remainderUnsigned keeps the unsigned reading Python uses.
        val head = ByteBuffer.wrap(digest, 0, 8).long
        // Locale.ROOT: a device locale with non-ASCII digits must not change the code.
        return String.format(Locale.ROOT, "%06d", java.lang.Long.remainderUnsigned(head, 1_000_000L))
    }

    /** Lowercase hex SHA-256 of a certificate DER (the leaf seen on first contact, or a CA). */
    fun derSha256(der: ByteArray): String = hex(sha256(der))

    /** Lowercase hex SHA-256 of the first PEM certificate's DER. Throws when [pem] has none. */
    fun derSha256(pem: String): String {
        val body = FIRST_PEM.find(pem)?.groupValues?.get(1) ?: throw IllegalArgumentException("no PEM certificate found")
        return derSha256(Base64.getMimeDecoder().decode(body))
    }

    /**
     * First 16 hex of a DER SHA-256, upper case, in groups of four joined by '-' (D-341 4). Stricter than Python,
     * which formats any text: the input must be a whole 64-hex digest.
     */
    fun fingerprintFromSha256(derSha256Hex: String): String {
        require(FINGERPRINT_INPUT.matches(derSha256Hex)) { "expected a 64-hex SHA-256" }
        return derSha256Hex.substring(0, 16).uppercase().chunked(4).joinToString("-")
    }

    fun siteFingerprint(caPem: String): String = fingerprintFromSha256(derSha256(caPem))

    fun siteFingerprint(caDer: ByteArray): String = fingerprintFromSha256(derSha256(caDer))

    /**
     * True when two fingerprints name the same CA. Not in pairing.py (the installer compares by eye); here for the
     * app's own checks. Case, spaces and dashes are ignored, and both must carry exactly 16 hex digits.
     */
    fun sameFingerprint(a: String, b: String): Boolean {
        fun canonical(text: String): String? =
            text.filterNot { it == '-' || it.isWhitespace() }.uppercase().takeIf { Regex("^[0-9A-F]{16}$").matches(it) }
        val left = canonical(a) ?: return false
        return left == canonical(b)
    }

    /**
     * Null when a discovery record may receive a pairing request, else a reason (D-341 14, 17). [host] is the
     * record's resolved host name (null when unknown); [txt] is the TXT map Android NSD hands over.
     *
     * Robot `_rosy._tcp` records run through the app's robot parser and are then `not_overhead`. The app has no
     * Fleet record parser, so any other accepted-looking type is `not_overhead` only for `_rosy-fleet._tcp`
     * and `wrong_type` otherwise (Python classifies a Fleet record first).
     */
    fun pairable(serviceType: String, host: String?, address: String?, port: Int, txt: Map<String, ByteArray?>): String? =
        when (normalizeServiceType(serviceType)) {
            normalizeServiceType(OverheadServiceRecord.SERVICE_TYPE) ->
                OverheadServiceRecord.rejection(serviceType, host, port, txt)
                    ?: if (txt["pair"]?.toString(UTF_8)?.trim() == PROTO) null else "no_pair"
            normalizeServiceType(RobotCoreServiceRecord.SERVICE_TYPE) ->
                RobotCoreServiceRecord.rejection(serviceType, address, port, txt) ?: "not_overhead"
            "_rosy-fleet._tcp" -> "not_overhead"
            else -> "wrong_type"
        }

    private fun sha256(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(bytes)

    private fun hex(bytes: ByteArray): String = bytes.joinToString("") { String.format(Locale.ROOT, "%02x", it.toInt() and 0xFF) }
}
