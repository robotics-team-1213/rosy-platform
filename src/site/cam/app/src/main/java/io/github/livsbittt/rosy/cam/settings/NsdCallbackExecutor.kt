package io.github.livsbittt.rosy.cam.settings

import java.util.concurrent.Executor
import java.util.concurrent.RejectedExecutionException

/** Executor boundary for callbacks that Android NSD can deliver after a browse ends. */
internal class NsdCallbackExecutor(private val delegate: Executor) : Executor {
    override fun execute(command: Runnable) {
        try {
            delegate.execute(command)
        } catch (_: RejectedExecutionException) {
            // Unregister is asynchronous. Android can dispatch its completion
            // after the browse scheduler closes; it must not crash NSD's thread.
        }
    }
}
