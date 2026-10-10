package io.github.livsbittt.rosy.pilot

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.Executors

class GroupCommandFanoutTest {
    @Test fun oneHeldInputReachesBothRobots() {
        val workers = Executors.newFixedThreadPool(2)
        try {
            val a = mutableListOf<String>(); val b = mutableListOf<String>()
            val fanout = GroupCommandFanout(workers, { body -> synchronized(a) { a.add(body) }; 200 },
                { body -> synchronized(b) { b.add(body) }; 200 })
            assertTrue(fanout.send(0.08, -0.12))
            assertEquals(listOf("{\"linear\":0.08,\"angular\":-0.12}"), a)
            assertEquals(a, b)
        } finally { workers.shutdownNow() }
    }

    @Test fun oneRobotRefusalRequestsZeroOnBoth() {
        val workers = Executors.newFixedThreadPool(2)
        try {
            val a = mutableListOf<String>(); val b = mutableListOf<String>()
            val fanout = GroupCommandFanout(workers, { body -> synchronized(a) { a.add(body) }; if (body.contains("0.08")) 409 else 200 },
                { body -> synchronized(b) { b.add(body) }; 200 })
            assertFalse(fanout.send(0.08, 0.0))
            assertEquals(2, a.size)
            assertEquals(a, b)
            assertEquals("{\"linear\":0,\"angular\":0}", a.last())
        } finally { workers.shutdownNow() }
    }

    @Test fun transportFailureStillRequestsZeroFromOtherRobot() {
        val workers = Executors.newFixedThreadPool(2)
        try {
            val b = mutableListOf<String>()
            val fanout = GroupCommandFanout(workers, { throw IllegalStateException("offline") },
                { body -> synchronized(b) { b.add(body) }; 200 })
            assertFalse(fanout.send(0.08, 0.0))
            assertEquals(listOf("{\"linear\":0.08,\"angular\":0.0}", "{\"linear\":0,\"angular\":0}"), b)
        } finally { workers.shutdownNow() }
    }
}
