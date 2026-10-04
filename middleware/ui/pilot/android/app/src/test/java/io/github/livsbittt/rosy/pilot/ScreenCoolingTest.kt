package io.github.livsbittt.rosy.pilot

import io.github.livsbittt.rosy.cam.health.DeviceHealth
import io.github.livsbittt.rosy.cam.health.ScreenCoolingPolicy
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.Executor

class ScreenCoolingTest {
    @Test fun supersededCoolingShutdownCannotStrandDiscoveryOrFinishNewSleep() {
        val sleep = PendingScreenSleep()
        val policy = ScreenCoolingPolicy()
        assertTrue(policy.requestSleep(DeviceHealth(85, false, 32.0, 3)))
        sleep.begin(1)
        assertTrue(sleep.active)
        // Retry/back revokes the pending operation while its IO completion is delayed.
        sleep.revoke()
        assertFalse(sleep.finish(1))
        policy.requestSleep(DeviceHealth(85, false, 32.0, 1))
        assertFalse(policy.coolingRequired || sleep.active)
        sleep.begin(2)
        assertFalse(sleep.finish(1))
        assertTrue(sleep.active)
        assertTrue(sleep.finish(2))
        assertFalse(sleep.active)
    }
    @Test fun screenProtectionUsesDeviceThermalSeverityAndRecoveryHysteresis() {
        val policy = ScreenCoolingPolicy()
        fun sample(thermal: Int) = DeviceHealth(85, false, 32.0, thermal)
        assertFalse(policy.requestSleep(sample(2)))
        assertTrue(policy.requestSleep(sample(3)))
        assertFalse(policy.requestSleep(sample(3)))
        assertFalse(policy.requestSleep(sample(2)))
        assertFalse(policy.requestSleep(sample(1)))
        assertTrue(policy.requestSleep(sample(3)))
    }
    @Test fun olderAndroidUsesBatteryTemperatureWithoutRepeatedSleep() {
        val policy = ScreenCoolingPolicy()
        fun sample(c: Double) = DeviceHealth(85, false, c)
        assertFalse(policy.requestSleep(sample(44.9)))
        assertTrue(policy.requestSleep(sample(45.0)))
        assertFalse(policy.requestSleep(sample(42.0)))
        assertFalse(policy.requestSleep(sample(41.0)))
        assertTrue(policy.requestSleep(sample(45.0)))
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
