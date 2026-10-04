package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class DiscoverySupervisorTest {
    private var time = 100L
    private fun supervisor() = DiscoverySupervisor { time }
    @Test fun stalledQueryWaitsForDeathBeforeReplacement() {
        val state = supervisor(); val old = state.start(); state.connected(old); state.queryStarted(old, 5)
        time += 11999; assertEquals(DiscoverySupervisor.Action.NONE, state.poll())
        time++; assertEquals(DiscoverySupervisor.Action.RETIRE, state.poll()); assertFalse(state.accepts(old))
        time += 1000; assertEquals(DiscoverySupervisor.Action.NONE, state.poll())
        state.died(old); time += 999; assertEquals(DiscoverySupervisor.Action.NONE, state.poll())
        time++; assertEquals(DiscoverySupervisor.Action.BIND, state.poll()); assertTrue(state.accepts(state.epoch))
    }
    @Test fun normalCompletionAndEmptyNetworkDoNotRestart() {
        val state = supervisor(); val token = state.start(); state.connected(token)
        time += 600000; assertEquals(DiscoverySupervisor.Action.NONE, state.poll())
        state.queryStarted(token, 1); state.queryEnded(token, 0)
        time += 12000; assertEquals(DiscoverySupervisor.Action.RETIRE, state.poll())
        val healthy = supervisor(); val other = healthy.start(); healthy.connected(other)
        healthy.queryStarted(other, 8); healthy.queryEnded(other, 8)
        time += 12000; assertEquals(DiscoverySupervisor.Action.NONE, healthy.poll())
    }
    @Test fun lateEventsCannotCompleteReplacementQuery() {
        val state = supervisor(); val old = state.start(); state.connected(old)
        state.failed(old); state.died(old); time += 1000; state.poll()
        val next = state.epoch; state.connected(next); state.queryStarted(next, 4)
        state.queryEnded(old, 4); assertFalse(state.acceptsEvent(old, time))
        time += 12000; assertEquals(DiscoverySupervisor.Action.RETIRE, state.poll())
    }
    @Test fun monotonicEventsRejectFutureAndExpiredMessages() {
        val state = supervisor(); val token = state.start()
        assertTrue(state.acceptsEvent(token, time)); assertFalse(state.acceptsEvent(token, time + 1))
        time += 60000; assertFalse(state.acceptsEvent(token, 100))
    }
    @Test fun stopCancelsDeadlineAndBackoff() {
        val state = supervisor(); val old = state.start(); state.failed(old); state.died(old); state.stop()
        time += 600000; assertEquals(DiscoverySupervisor.Action.NONE, state.poll()); assertFalse(state.accepts(old))
        state.died(old); assertEquals(DiscoverySupervisor.Action.NONE, state.poll())
    }
    @Test fun threeRestartsPerRollingFiveMinutesAndManualRetry() {
        val state = supervisor(); var token = state.start()
        repeat(3) { index ->
            state.connected(token); state.failed(token); state.died(token)
            time += 1000L shl index; assertEquals(DiscoverySupervisor.Action.BIND, state.poll()); token = state.epoch
        }
        state.failed(token); state.died(token); time += 10000
        assertEquals(DiscoverySupervisor.Action.NONE, state.poll()); assertTrue(state.status.contains("다시 찾기"))
        val manual = supervisor(); assertTrue(manual.accepts(manual.start()))
    }
    @Test fun rollingWindowRestoresBudgetAndDuplicateDeathIsHarmless() {
        val state = supervisor(); val old = state.start(); state.failed(old); state.died(old); state.died(old)
        time += 1000; assertEquals(DiscoverySupervisor.Action.BIND, state.poll())
        val next = state.epoch; state.connected(next); time += 300000
        state.failed(next); state.died(next); time += 1000
        assertEquals(DiscoverySupervisor.Action.BIND, state.poll())
    }
    @Test fun missingCleanupExhaustsWithoutRebind() {
        val state = supervisor(); val token = state.start(); state.connected(token); state.failed(token)
        time += 12000; assertEquals(DiscoverySupervisor.Action.NONE, state.poll())
        state.died(token); time += 10000; assertEquals(DiscoverySupervisor.Action.NONE, state.poll())
        assertTrue(state.status.contains("다시 찾기"))
    }
    @Test fun oneHealthyWatchCannotMaskAnotherStalledWatch() {
        val state = supervisor(); val token = state.start(); state.connected(token)
        state.queryStarted(token, 1); time += 1000; state.queryStarted(token, 2)
        state.queryEnded(token, 2); state.queryStarted(token, 1)
        time += 11000; assertEquals(DiscoverySupervisor.Action.RETIRE, state.poll())
    }
    @Test fun replacementAdapterWaitsForAllRetiringBinders() {
        val fence = DiscoveryRetirementFence(); val old = Any(); val pendingConnection = Any(); val replacement = Any()
        var binds = 0
        fence.hold(old); fence.hold(pendingConnection); fence.await(replacement) { binds++ }
        assertEquals(0, binds); fence.died(old); assertEquals(0, binds)
        fence.died(pendingConnection); assertEquals(1, binds)
        fence.died(old); assertEquals(1, binds)
    }
    @Test fun stoppedReplacementCannotWakeAfterOldChildDies() {
        val fence = DiscoveryRetirementFence(); val old = Any(); val replacement = Any(); var binds = 0
        fence.hold(old); fence.await(replacement) { binds++ }; fence.cancel(replacement); fence.died(old)
        assertEquals(0, binds)
    }
    @Test fun releaseReconcilesAlreadyDeadBinderBeforeQueuedDeathRuns() {
        val fence = DiscoveryRetirementFence(); val old = Any(); val replacement = Any(); var binds = 0
        fence.hold(old); fence.await(replacement) { binds++ }
        fence.hold(old, alive = false); assertEquals(1, binds)
        fence.died(old); assertEquals(1, binds)
    }
    @Test fun queuedDeathSurvivesReplacementStopOrdering() {
        val fence = DiscoveryRetirementFence(); val old = Any(); val stopped = Any(); val replacement = Any(); var binds = 0
        fence.hold(old); fence.await(stopped) { fail("stopped adapter rebound") }; fence.cancel(stopped)
        fence.await(replacement) { binds++ }; fence.died(old)
        assertEquals(1, binds)
    }
    @Test fun connectedTransportWithoutStartAcknowledgementStillTimesOut() {
        val state = supervisor(); state.start()
        time += 12000; assertEquals(DiscoverySupervisor.Action.RETIRE, state.poll())
    }
    private fun session(store: CandidateStore, candidate: Candidate) = LobbySession(
        RobotTarget("rosy_01", candidate.host, candidate.port, "test-private-session-token"), candidate.secure,
        Instant.now().plusSeconds(600), candidate, store)
    @Test fun approvedSessionSurvivesResolverFailureUntilOriginalTtl() {
        val store = CandidateStore(); val ledger = DiscoveryPresenceLedger(store) { time }
        val candidate = Candidate("192.168.1.201", 8080, listOf("192.168.1.201"), "robot", "rosy_01", false)
        ledger.found("robot", 1); store.resolved("robot", ledger.generation("robot", 1)!!, candidate); ledger.resolved("robot", 1, time)
        val approved = session(store, candidate); assertTrue(approved.authorized())
        val state = supervisor(); val token = state.start(); state.connected(token); state.failed(token); ledger.newEpoch()
        assertTrue(approved.authorized()); assertNull(ledger.generation("robot", 1))
        time += 59999; assertFalse(ledger.expire()); assertTrue(approved.authorized())
        // A new child announcing the same name does not renew an old resolution's TTL.
        ledger.found("robot", 2); time++; assertTrue(ledger.expire()); assertFalse(approved.authorized())
    }
    @Test fun realLossAndConflictingIdentityStillRevokeApprovedSession() {
        val store = CandidateStore(); val ledger = DiscoveryPresenceLedger(store) { time }
        val candidate = Candidate("192.168.1.201", 8080, listOf("192.168.1.201"), "robot", "rosy_01", false)
        ledger.found("robot", 1); store.resolved("robot", ledger.generation("robot", 1)!!, candidate)
        val approved = session(store, candidate); assertTrue(approved.authorized())
        assertFalse(ledger.lost("robot", 0)); assertTrue(approved.authorized())
        assertTrue(ledger.lost("robot", 1)); assertFalse(approved.authorized())
        ledger.found("robot", 2); store.resolved("robot", ledger.generation("robot", 2)!!, candidate.copy(robotId = "rosy_02"))
        assertFalse(approved.authorized())
    }
}
