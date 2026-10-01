package io.github.livsbittt.rosy.cam.link

/**
 * Client failure classes of D-370 5.5 plus D-391 1 `not_discovered`, one class per observed input. The machine
 * source is `test/fixtures/protocol/failure-classes.v1.json` (same rules as core_common `failure_class.py`);
 * `FailureClassTest` runs every vector case through this object.
 *
 * Class and behaviour are separate: this says what kind of failure it was; [OverheadLink] decides whether to
 * retry. Both TLS kinds are `tls_untrusted` here, yet a pin mismatch on a manual route stops the link and the
 * first one on a discovered route browses again (review M3).
 */
object FailureClass {
    const val UNREACHABLE = "unreachable"
    const val REFUSED = "refused"
    const val UNKNOWN_HOST = "unknown_host"
    const val TLS_UNTRUSTED = "tls_untrusted"
    const val AUTH_FINAL = "auth_final"
    const val AUTH_RETRY = "auth_retry"
    const val FORBIDDEN = "forbidden"
    const val PROTOCOL_MISMATCH = "protocol_mismatch"
    const val BUSY = "busy"
    const val CONFLICT = "conflict"
    const val NOT_DISCOVERED = "not_discovered"

    val ALL = listOf(
        UNREACHABLE, REFUSED, UNKNOWN_HOST, TLS_UNTRUSTED, AUTH_FINAL, AUTH_RETRY,
        FORBIDDEN, PROTOCOL_MISMATCH, BUSY, CONFLICT, NOT_DISCOVERED,
    )

    /**
     * WebSocket close code to class. A 4400 whose [reason] is a pre-1013 hello wait (`""`, `"no hello"`; a
     * missing reason counts as empty) is `busy`, any other 4400 `protocol_mismatch`, as in
     * [OverheadLink.closeOutcome]. A code outside the table falls back to `unreachable`.
     */
    fun forClose(code: Int, reason: String? = null): String = when (code) {
        Protocol.CLOSE_BAD_PROTO -> if (Protocol.isIncompatibleClose(code, reason.orEmpty())) PROTOCOL_MISMATCH else BUSY
        Protocol.CLOSE_UNAUTHORIZED -> AUTH_FINAL
        Protocol.CLOSE_FORBIDDEN -> FORBIDDEN
        Protocol.CLOSE_REPLACED -> CONFLICT
        Protocol.CLOSE_CREDENTIAL_UNKNOWN -> AUTH_RETRY
        Protocol.CLOSE_TRY_AGAIN -> BUSY
        else -> UNREACHABLE
    }

    /**
     * HTTP status on the upgrade or a REST call to class: the listed statuses, then any other 4xx
     * `protocol_mismatch` and 5xx `busy`. Null for a status that is not a failure.
     */
    fun forHttp(status: Int): String? = when (status) {
        401 -> AUTH_FINAL
        403 -> FORBIDDEN
        409 -> CONFLICT
        429, 503 -> BUSY
        in 400..499 -> PROTOCOL_MISMATCH
        in 500..599 -> BUSY
        else -> null
    }

    /** Transport failure to class; null for [NetworkFailure.OTHER]. */
    fun forNetwork(kind: NetworkFailure): String? = when (kind) {
        NetworkFailure.UNREACHABLE -> UNREACHABLE
        NetworkFailure.REFUSED -> REFUSED
        NetworkFailure.UNKNOWN_HOST -> UNKNOWN_HOST
        NetworkFailure.TLS, NetworkFailure.TLS_PIN -> TLS_UNTRUSTED
        NetworkFailure.NOT_DISCOVERED -> NOT_DISCOVERED
        NetworkFailure.CONFLICT -> CONFLICT
        NetworkFailure.OTHER -> null
    }

    /**
     * The vector's transport vocabulary (`timeout`, `no_route`, `connection_refused`, `dns_failure`,
     * `tls_handshake`, `tls_pin_mismatch`) as the [NetworkFailure] the app classifies those exceptions to.
     * Null for a name outside that closed vocabulary.
     */
    fun networkFailureFor(transport: String): NetworkFailure? = when (transport) {
        "timeout", "no_route" -> NetworkFailure.UNREACHABLE
        "connection_refused" -> NetworkFailure.REFUSED
        "dns_failure" -> NetworkFailure.UNKNOWN_HOST
        "tls_handshake" -> NetworkFailure.TLS
        "tls_pin_mismatch" -> NetworkFailure.TLS_PIN
        else -> null
    }

    /** Discovery outcome to class; only `no_match_within_timeout` exists (D-391 1). */
    fun forDiscovery(outcome: String): String? = if (outcome == "no_match_within_timeout") NOT_DISCOVERED else null
}
