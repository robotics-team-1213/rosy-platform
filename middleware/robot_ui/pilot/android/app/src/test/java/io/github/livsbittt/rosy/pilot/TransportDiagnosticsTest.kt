package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test

class TransportDiagnosticsTest {
    @Test fun recordsLocalAndUpstreamTimeSeparatelyWithoutRequestDetails() {
        val records = mutableListOf<String>()
        val stats = TransportDiagnostics(emit = records::add)
        stats.http("/api/v1/teleop", 12, 230, 200)
        stats.http("/api/v1/auth/pair?token=private-fixture", 3, 10, 401)
        stats.rejected(); stats.socketClosed(4403)
        val summary = stats.summary()
        assertTrue(summary.contains("control count=1 local_ms=12 upstream_ms=230 failures=0"))
        assertTrue(summary.contains("background_rejected=1 ws_close=4403"))
        assertFalse(summary.contains("private-fixture")); assertFalse(summary.contains("/api/"))
        assertFalse(records.joinToString().contains("private-fixture"))
    }

    @Test fun repeatedFailuresUseFixedBucketsAndRateLimitedLogging() {
        var now = 0L
        val records = mutableListOf<String>()
        val stats = TransportDiagnostics({ now }, records::add)
        repeat(10_000) { stats.http("/unknown/$it", 1, 400, 0) }
        assertEquals(1, records.size)
        assertTrue(stats.summary().contains("other count=10000 local_ms=1 upstream_ms=400 failures=10000"))
        assertTrue(stats.summary().length < 600)
        now = 5000
        stats.http("/api/v1/robot/state", 2, 25, 200)
        assertEquals(2, records.size)
    }

    @Test fun unavailableLoggerCannotBreakTransport() {
        val stats = TransportDiagnostics(emit = { error("logger unavailable") })
        stats.http("/api/v1/teleop", 0, 400, 0)
        assertTrue(stats.summary().contains("failures=1"))
    }
}
