package io.github.livsbittt.rosy.overhead.link

import java.util.concurrent.atomic.AtomicLong

/**
 * Single-slot sender policy (design section 3, D-136 6): a frame is sent only when nothing is
 * still queued on the socket; otherwise the new frame is dropped and counted. No queue grows.
 */
class LatestOnlyPolicy {
    private val droppedCount = AtomicLong()

    val dropped: Long get() = droppedCount.get()

    fun admit(queuedBytes: Long): Boolean {
        if (queuedBytes > 0) {
            droppedCount.incrementAndGet()
            return false
        }
        return true
    }

    /** Counts a drop decided elsewhere (for example a JPEG larger than `max_bytes`). */
    fun countDrop() {
        droppedCount.incrementAndGet()
    }

    fun resetCount() {
        droppedCount.set(0)
    }
}
