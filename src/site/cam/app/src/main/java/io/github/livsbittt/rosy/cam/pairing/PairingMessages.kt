package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.settings.PairingUri
import io.github.livsbittt.rosy.cam.settings.SiteLink
import io.github.livsbittt.rosy.cam.settings.SiteLinkRecord
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets.UTF_8
import org.json.JSONException
import org.json.JSONObject
import org.json.JSONTokener

/**
 * `rosy-pair/1` JSON shapes (D-341 2, 3, 8). The request, reveal and result rules are the vector's
 * (`pairing.v1.json` `request_cases`, `reveal_cases`, `result_cases`) in pairing.py's check order. The create,
 * poll and confirm replies are not in the vector; their shapes follow rosy-00's S2 server (a83653e3,
 * `fleet/server/pairing.py`) and stay provisional until that lands on main.
 *
 * Phone-sent bodies ([PairingRequest], [PairingReveal]) reject unknown fields like the server (`extra=forbid`);
 * server replies accept and ignore unknown fields.
 */
sealed interface Parsed<out T> {
    data class Valid<T>(val value: T) : Parsed<T>
    data class Invalid(val reason: String) : Parsed<Nothing>
}

/** `POST …/requests` body. Only digests leave the phone: the nonce and poll secret stay local until reveal/poll. */
data class PairingRequest(
    val deviceLabel: String,
    val appVersion: String,
    val clientCommit: String,
    val pollSecretSha256: String,
) {
    fun toJson(): ByteArray = JSONObject()
        .put("proto", Pairing.PROTO)
        .put("role", Pairing.ROLE)
        .put("device_label", deviceLabel)
        .put("app_version", appVersion)
        .put("client_commit", clientCommit)
        .put("poll_secret_sha256", pollSecretSha256)
        .toString()
        .toByteArray(UTF_8)

    companion object {
        val FIELDS = listOf("proto", "role", "device_label", "app_version", "client_commit", "poll_secret_sha256")
        private val LABEL_LIMITS = mapOf("device_label" to 64, "app_version" to 32)

        /** Reason a request body is refused, or null. Size is checked before parsing (pairing.py order). */
        fun validate(raw: ByteArray): String? {
            if (raw.size > Pairing.MAX_REQUEST_BYTES) return "too_large"
            val body = PairingJson.readObject(raw) ?: return "not_object"
            // keys(), not keySet(): Android's org.json has no keySet.
            if (body.keys().asSequence().any { it !in FIELDS }) return "unknown_field"
            if (FIELDS.any { !body.has(it) }) return "missing_field"
            if (body.opt("proto") != Pairing.PROTO) return "proto"
            if (body.opt("role") != Pairing.ROLE) return "role"
            for ((name, limit) in LABEL_LIMITS) if (!cleanLabel(body.opt(name), limit)) return "bad_value"
            for (name in listOf("client_commit", "poll_secret_sha256")) {
                val value = body.opt(name)
                if (value !is String || !Pairing.SHA256_HEX.matches(value)) return "bad_value"
            }
            return null
        }

        fun parse(raw: ByteArray): Parsed<PairingRequest> {
            validate(raw)?.let { return Parsed.Invalid(it) }
            val body = PairingJson.readObject(raw)!!
            return Parsed.Valid(
                PairingRequest(
                    body.getString("device_label"),
                    body.getString("app_version"),
                    body.getString("client_commit"),
                    body.getString("poll_secret_sha256"),
                ),
            )
        }

        /**
         * pairing.py `_clean_label`: non-blank, at most [limit] code points (Python `len`), no C0 control or DEL.
         * Kotlin `trim` and Python `strip` differ only on rare Unicode spaces; no vector case covers them.
         */
        private fun cleanLabel(value: Any?, limit: Int): Boolean {
            if (value !is String) return false
            val trimmed = value.trim()
            return trimmed.isNotEmpty() && trimmed.codePointCount(0, trimmed.length) <= limit &&
                value.codePointCount(0, value.length) <= limit && value.none { it.code < 32 || it.code == 127 }
        }
    }
}

/** `POST …/requests/{id}/reveal` body: the nonce whose digest the request committed to. */
data class PairingReveal(val clientNonce: String) {
    fun toJson(): ByteArray = JSONObject().put("client_nonce", clientNonce).toString().toByteArray(UTF_8)

    companion object {
        fun validate(raw: ByteArray): String? {
            if (raw.size > Pairing.MAX_REQUEST_BYTES) return "too_large"
            val body = PairingJson.readObject(raw) ?: return "not_object"
            if (body.keys().asSequence().any { it != "client_nonce" }) return "unknown_field"
            if (!body.has("client_nonce")) return "missing_field"
            val nonce = body.opt("client_nonce")
            if (nonce !is String || !Pairing.SECRET_PATTERN.matches(nonce)) return "bad_value"
            return null
        }

        fun parse(raw: ByteArray): Parsed<PairingReveal> =
            validate(raw)?.let { Parsed.Invalid(it) }
                ?: Parsed.Valid(PairingReveal(PairingJson.readObject(raw)!!.getString("client_nonce")))
    }
}

/** The one-time result inside an approved poll (D-341 8). [token] is the camera credential; never printed. */
data class PairingResult(
    val siteName: String,
    val sourceId: String,
    val tlsHost: String,
    val siteCaPem: String,
    val token: String,
    val credentialId: String,
    val expiresAt: String,
) {
    override fun toString(): String =
        "PairingResult(siteName=$siteName, sourceId=$sourceId, tlsHost=$tlsHost, token=<redacted>, " +
            "credentialId=$credentialId, expiresAt=$expiresAt)"

    companion object {
        val FIELDS = listOf(
            "proto", "role", "site_name", "source_id", "tls_host", "site_ca_pem", "token", "credential_id", "expires_at",
        )
        val CREDENTIAL_ID_PATTERN = Regex("^[A-Za-z0-9_-]{1,64}$")

        /** Reason a delivered result is unusable, or null. Unknown fields are ignored; JSON null is missing. */
        fun validate(result: Any?): String? {
            if (result !is JSONObject) return "not_object"
            if (FIELDS.any { PairingJson.value(result, it) == null }) return "missing_field"
            if (result.opt("proto") != Pairing.PROTO) return "proto"
            if (result.opt("role") != Pairing.ROLE) return "role"
            val siteName = result.opt("site_name")
            if (siteName !is String || siteName.isBlank()) return "bad_value"
            val sourceId = result.opt("source_id")
            if (sourceId !is String || !PairingUri.SOURCE_PATTERN.matches(sourceId)) return "bad_value"
            val token = result.opt("token")
            if (token !is String || !Pairing.SECRET_PATTERN.matches(token)) return "bad_value"
            val credentialId = result.opt("credential_id")
            if (credentialId !is String || !CREDENTIAL_ID_PATTERN.matches(credentialId)) return "bad_value"
            val tlsHost = result.opt("tls_host")
            if (tlsHost !is String || !SiteLink.isTlsHost(tlsHost)) return "bad_tls_host"
            SiteLinkRecord.caPemReason(result.opt("site_ca_pem"))?.let { return it }
            if (!SiteLinkRecord.isUtcTimestamp(result.opt("expires_at"))) return "bad_expires_at"
            return null
        }

        fun parse(result: Any?): Parsed<PairingResult> {
            validate(result)?.let { return Parsed.Invalid(it) }
            val r = result as JSONObject
            return Parsed.Valid(
                PairingResult(
                    r.getString("site_name"), r.getString("source_id"), r.getString("tls_host"),
                    r.getString("site_ca_pem"), r.getString("token"), r.getString("credential_id"),
                    r.getString("expires_at"),
                ),
            )
        }
    }
}

/** `201` reply to the request: the id to poll, the server's nonce for the code, and the pending deadline. */
data class PairingCreated(val requestId: String, val serverNonce: String, val expiresAt: String) {
    companion object {
        /** The id goes into URL paths, so it is held to a path-safe pattern (S2 issues `pr-` + 16 base64url). */
        val REQUEST_ID_PATTERN = Regex("^[A-Za-z0-9_-]{1,64}$")

        fun parse(raw: ByteArray): Parsed<PairingCreated> {
            val body = PairingJson.readObject(raw) ?: return Parsed.Invalid("not_object")
            val id = PairingJson.value(body, "request_id")
            val nonce = PairingJson.value(body, "server_nonce")
            val expires = PairingJson.value(body, "expires_at")
            if (id == null || nonce == null || expires == null) return Parsed.Invalid("missing_field")
            if (id !is String || !REQUEST_ID_PATTERN.matches(id)) return Parsed.Invalid("bad_value")
            if (nonce !is String || !Pairing.SECRET_PATTERN.matches(nonce)) return Parsed.Invalid("bad_value")
            if (!SiteLinkRecord.isUtcTimestamp(expires)) return Parsed.Invalid("bad_expires_at")
            return Parsed.Valid(PairingCreated(id, nonce, expires as String))
        }
    }
}

/** One poll reply (`GET …/requests/{id}`). */
sealed interface PollReply {
    /** `pending` (not revealed yet) or `revealed` (waiting for the operator's code). */
    data class Waiting(val state: String) : PollReply

    data class Approved(val result: PairingResult) : PollReply

    /** `rejected` or `expired`: the request is over. */
    data class Closed(val state: String) : PollReply

    companion object {
        private val WAITING = setOf("pending", "revealed")
        private val CLOSED = setOf("rejected", "expired")

        /** Invalid reasons: `not_object`, `missing_field`, `bad_value` (unknown state), or a result reason. */
        fun parse(raw: ByteArray): Parsed<PollReply> {
            val body = PairingJson.readObject(raw) ?: return Parsed.Invalid("not_object")
            val state = PairingJson.value(body, "state") ?: return Parsed.Invalid("missing_field")
            if (state !is String) return Parsed.Invalid("bad_value")
            return when (state) {
                in WAITING -> Parsed.Valid(Waiting(state))
                in CLOSED -> Parsed.Valid(Closed(state))
                "approved" -> {
                    // An absent result is the reply's own missing field; a present one gets the result rules.
                    val raw = PairingJson.value(body, "result") ?: return Parsed.Invalid("missing_field")
                    when (val result = PairingResult.parse(raw)) {
                        is Parsed.Valid -> Parsed.Valid(Approved(result.value))
                        is Parsed.Invalid -> result
                    }
                }
                else -> Parsed.Invalid("bad_value")
            }
        }
    }
}

/** `POST …/requests/{id}/confirm` body and its reply check. */
data class PairingConfirm(val credentialId: String) {
    fun toJson(): ByteArray = JSONObject().put("credential_id", credentialId).toString().toByteArray(UTF_8)

    /** Null when [raw] confirms exactly this credential, else a reason. */
    fun replyReason(raw: ByteArray): String? {
        val body = PairingJson.readObject(raw) ?: return "not_object"
        if (body.opt("state") != "confirmed") return "bad_value"
        if (body.opt("credential_id") != credentialId) return "bad_value"
        return null
    }
}

internal object PairingJson {
    /**
     * One JSON object and nothing after it, from strict UTF-8; null otherwise. org.json is more lenient than
     * Python's json (unquoted keys, single quotes) and rejects duplicate keys that Python would take last-wins.
     */
    fun readObject(raw: ByteArray): JSONObject? {
        val text = try {
            UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(raw))
                .toString()
        } catch (e: CharacterCodingException) {
            return null
        }
        return try {
            val tokener = JSONTokener(text)
            val value = tokener.nextValue()
            if (value is JSONObject && tokener.nextClean() == 0.toChar()) value else null
        } catch (e: JSONException) {
            null
        }
    }

    /** The field, with JSON null read as absent (pairing.py `result.get(name) is None`). */
    fun value(body: JSONObject, name: String): Any? = body.opt(name)?.takeUnless { it == JSONObject.NULL }
}
