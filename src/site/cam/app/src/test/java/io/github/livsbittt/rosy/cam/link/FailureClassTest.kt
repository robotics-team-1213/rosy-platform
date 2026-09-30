package io.github.livsbittt.rosy.cam.link

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * D-391 4항 1단계 minimum rows. The shared vector `test/fixtures/protocol/failure-classes.v1.json` was not on
 * main when this was written; when it lands, these rows come from it instead of this table.
 */
class FailureClassTest {
    @Test
    fun closeCodes() {
        val rows = mapOf(
            4400 to FailureClass.PROTOCOL_MISMATCH,
            4401 to FailureClass.AUTH_FINAL,
            4403 to FailureClass.FORBIDDEN,
            4409 to FailureClass.CONFLICT,
            4503 to FailureClass.AUTH_RETRY,
            1013 to FailureClass.BUSY,
        )
        rows.forEach { (code, expected) -> assertEquals("close $code", expected, FailureClass.forClose(code)) }
        assertEquals(FailureClass.BUSY, FailureClass.forClose(4400, "no hello"))
        assertNull(FailureClass.forClose(1000))
    }

    @Test
    fun httpStatuses() {
        val rows = mapOf(
            401 to FailureClass.AUTH_FINAL,
            403 to FailureClass.FORBIDDEN,
            409 to FailureClass.CONFLICT,
            429 to FailureClass.BUSY,
            503 to FailureClass.BUSY,
        )
        rows.forEach { (status, expected) -> assertEquals("HTTP $status", expected, FailureClass.forHttp(status)) }
        assertNull(FailureClass.forHttp(200))
    }

    @Test
    fun transportFailures() {
        assertEquals(FailureClass.NOT_DISCOVERED, FailureClass.forNetwork(NetworkFailure.NOT_DISCOVERED))
        assertEquals(FailureClass.TLS_UNTRUSTED, FailureClass.forNetwork(NetworkFailure.TLS_PIN))
        assertEquals(FailureClass.CONFLICT, FailureClass.forNetwork(NetworkFailure.CONFLICT))
        assertNull(FailureClass.forNetwork(NetworkFailure.OTHER))
    }
}
