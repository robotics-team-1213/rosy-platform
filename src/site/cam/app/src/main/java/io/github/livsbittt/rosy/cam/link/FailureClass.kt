package io.github.livsbittt.rosy.cam.link

/**
 * Client failure classes of D-370 5.5 plus D-391 1 `not_discovered`. The machine-readable source is the shared
 * vector `test/fixtures/protocol/failure-classes.v1.json` (D-391 4항 1단계, rosy-00). It was not on main when
 * this table was written, so these rows are the app's reading of D-341 11 and D-370 5.5; `FailureClassTest`
 * is the place to switch to the vector once it lands.
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

    /**
     * WebSocket close code to class; null for codes outside D-341 11 (normal closes and the like). A 4400 whose
     * [reason] is a receiver-side wait is `busy`, as in [OverheadLink.closeOutcome].
     */
    fun forClose(code: Int, reason: String = "incompatible"): String? = when (code) {
        Protocol.CLOSE_BAD_PROTO -> if (Protocol.isIncompatibleClose(code, reason)) PROTOCOL_MISMATCH else BUSY
        Protocol.CLOSE_UNAUTHORIZED -> AUTH_FINAL
        CLOSE_FORBIDDEN -> FORBIDDEN
        Protocol.CLOSE_REPLACED -> CONFLICT
        Protocol.CLOSE_CREDENTIAL_UNKNOWN -> AUTH_RETRY
        Protocol.CLOSE_TRY_AGAIN -> BUSY
        else -> null
    }

    /** HTTP status on the upgrade or a REST call to class; null for statuses outside the D-391 minimum rows. */
    fun forHttp(status: Int): String? = when (status) {
        401 -> AUTH_FINAL
        403 -> FORBIDDEN
        409 -> CONFLICT
        429, 503 -> BUSY
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

    /** D-341 11 close 4403: the credential is valid but not allowed for this source. */
    private const val CLOSE_FORBIDDEN = 4403
}
