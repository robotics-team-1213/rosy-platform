package io.github.livsbittt.rosy.cam.settings

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NsdCallbackExecutorTest {
    @Test
    fun activeBrowseReceivesCallbacks() {
        val scheduler = Executors.newSingleThreadScheduledExecutor()
        try {
            val called = CountDownLatch(1)
            NsdCallbackExecutor(scheduler).execute { called.countDown() }
            assertTrue(called.await(1, TimeUnit.SECONDS))
        } finally {
            scheduler.shutdownNow()
        }
    }

    @Test
    fun lateUnregistrationCallbackIsSafe() {
        val scheduler = Executors.newSingleThreadScheduledExecutor()
        val callbacks = NsdCallbackExecutor(scheduler)
        scheduler.shutdown()
        assertTrue(scheduler.awaitTermination(1, TimeUnit.SECONDS))
        var called = false
        callbacks.execute { called = true }
        assertFalse(called)
    }
}
