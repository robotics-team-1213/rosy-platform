package io.github.livsbittt.rosy.overhead.link

/** Sent frames per second and kbit/s over a sliding window, for the on-screen counters. */
class RateMeter(private val windowNanos: Long = 2_000_000_000L) {
    private val times = ArrayDeque<Long>()
    private val sizes = ArrayDeque<Int>()
    private var bytesInWindow = 0L

    @Synchronized
    fun record(nowNanos: Long, bytes: Int) {
        times.addLast(nowNanos)
        sizes.addLast(bytes)
        bytesInWindow += bytes
        evict(nowNanos)
    }

    @Synchronized
    fun fps(nowNanos: Long): Double {
        evict(nowNanos)
        return times.size / windowSeconds()
    }

    @Synchronized
    fun kbps(nowNanos: Long): Double {
        evict(nowNanos)
        return bytesInWindow * 8.0 / 1000.0 / windowSeconds()
    }

    @Synchronized
    fun clear() {
        times.clear()
        sizes.clear()
        bytesInWindow = 0
    }

    private fun windowSeconds(): Double = windowNanos / 1_000_000_000.0

    private fun evict(nowNanos: Long) {
        while (times.isNotEmpty() && nowNanos - times.first() >= windowNanos) {
            times.removeFirst()
            bytesInWindow -= sizes.removeFirst()
        }
    }
}
