package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test

class LinkStatusTest {
    @Test fun everyFailureNamesItsReason() {
        val cases = mapOf<Throwable, LinkReason>(
            PeerApprovalExpired() to LinkReason.APPROVAL_EXPIRED,
            PeerApprovalTimeout() to LinkReason.APPROVAL_TIMEOUT,
            PeerEnded("rejected") to LinkReason.APPROVAL_DENIED,
            PeerEnded("expired") to LinkReason.APPROVAL_TIMEOUT,
            PeerEnded("cancelled") to LinkReason.APPROVAL_CANCELLED,
            PeerEnded("superseded") to LinkReason.UNKNOWN,
            PeerKeyChanged() to LinkReason.IDENTITY_CHANGED,
            PeerRefused(404) to LinkReason.API_VERSION_TOO_OLD,
            PeerRefused(503) to LinkReason.CORE_NOT_READY,
            PeerRefused(429) to LinkReason.RATE_LIMITED,
            PeerRefused(409) to LinkReason.APPROVAL_REVOKED,
            PeerRefused(500) to LinkReason.REFUSED,
            java.net.ConnectException("refused") to LinkReason.ROBOT_UNREACHABLE,
            java.io.IOException("wrapped", java.net.SocketTimeoutException()) to LinkReason.ROBOT_UNREACHABLE,
            javax.net.ssl.SSLHandshakeException("pin") to LinkReason.CA_UNKNOWN,
            IllegalArgumentException("x") to LinkReason.UNKNOWN,
        )
        for ((error, reason) in cases) {
            assertEquals(error.toString(), reason, LinkStatus.reason(error))
            val text = LinkStatus.failure(error, secure = true)
            assertTrue(text, text.isNotBlank() && !text.contains(error.message ?: "\u0000"))
        }
    }
    @Test fun pendingSaysWhichRequestBothWaysAndTimeLeft() {
        val text = LinkStatus.pending("rosy-pinky-9dfk · rosy_26", "K7QM", 125)
        assertTrue(text.contains("요청 번호 K7QM") && text.contains("2:05") && text.contains("대시보드") && text.contains("Pair request"))
        assertTrue(LinkStatus.pending("r", "K7QM", -3).contains("0:00"))
        assertFalse(text.contains("CA "))
        // First contact: compare the LCD's CA line before typing the code (the card goes away on approval).
        assertTrue(LinkStatus.pending("r", "K7QM", 60, "0123456789abcdef" + "f".repeat(48)).contains("CA 0123 4567 89ab cdef"))
    }
    @Test fun codeFieldKeepsOnlyTheCodeAlphabet() {
        // A Korean keyboard sent Hangul into the field on the device walk; O, 0, I, 1 are not in the alphabet either.
        assertEquals("B2A", LinkStatus.codeFilter.filter("뮤B2O0A!", 0, 7, null, 0, 0).toString())
        assertNull(LinkStatus.codeFilter.filter("ABC234", 0, 6, null, 0, 0))
    }
    @Test fun caShortIsWhatTheLcdDraws() {
        assertEquals("0123 4567 89ab cdef", LinkStatus.caShort("0123456789abcdef" + "f".repeat(48)))
    }
}
