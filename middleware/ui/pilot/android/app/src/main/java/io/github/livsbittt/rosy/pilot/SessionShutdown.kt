package io.github.livsbittt.rosy.pilot

import java.util.concurrent.Executor

/** Waits for tracked zero/close and stale startup completions before a display-power action. */
object SessionShutdown {
    fun close(io: Executor, ui: Executor, disconnect: () -> Unit, done: (() -> Unit)? = null) {
        io.execute {
            disconnect()
            // UI completions can enqueue cleanup of a startup relay that never became tracked.
            if (done != null) ui.execute { io.execute { ui.execute { done() } } }
        }
    }
}
