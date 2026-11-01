package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.Executor

class ScreenSleepTest {
    @Test fun supersededScreenOffCannotStrandDiscoveryOrFinishNewSleep() {
        val sleep = PendingScreenSleep()
        sleep.begin(1)
        assertTrue(sleep.active)
        // Retry/back revokes the pending operation while its IO completion is delayed.
        sleep.revoke()
        assertFalse(sleep.finish(1))
        assertFalse(sleep.active)
        sleep.begin(2)
        assertFalse(sleep.finish(1))
        assertTrue(sleep.active)
        assertTrue(sleep.finish(2))
        assertFalse(sleep.active)
    }
    @Test fun screenPowerWaitsForZeroAndUnclaimedStartupRelayCleanup() {
        class Queue : Executor {
            val tasks = ArrayDeque<Runnable>()
            override fun execute(command: Runnable) { tasks.add(command) }
            fun next() = tasks.removeFirst().run()
        }
        val io = Queue(); val ui = Queue(); val events = mutableListOf<String>()
        // A startup completion is queued on UI before revocation and still owns its relay.
        ui.execute { io.execute { events.add("stale-close") } }
        SessionShutdown.close(io, ui, { events.add("zero"); events.add("tracked-close") }, { events.add("screen-off") })
        io.next(); assertEquals(listOf("zero", "tracked-close"), events)
        ui.next(); ui.next(); assertFalse(events.contains("screen-off"))
        io.next(); assertEquals("stale-close", events.last())
        io.next(); assertFalse(events.contains("screen-off"))
        ui.next(); assertEquals(listOf("zero", "tracked-close", "stale-close", "screen-off"), events)
    }
}
