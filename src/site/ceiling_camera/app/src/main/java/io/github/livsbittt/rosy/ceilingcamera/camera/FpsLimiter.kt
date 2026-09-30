package io.github.livsbittt.rosy.overhead.camera

/**
 * Admits a frame only when at least 1/[fps] seconds have passed since the last admitted frame.
 * [fps] follows the adapter's `config` and may change at runtime from another thread.
 */
class FpsLimiter(fps: Double) {
    @Volatile
    var fps: Double = checkFps(fps)
        set(value) {
            field = checkFps(value)
        }

    private var lastAdmittedNanos: Long? = null

    @Synchronized
    fun tryAdmit(nowNanos: Long): Boolean {
        val last = lastAdmittedNanos
        val intervalNanos = (1_000_000_000.0 / fps).toLong()
        if (last != null && nowNanos - last < intervalNanos) return false
        lastAdmittedNanos = nowNanos
        return true
    }

    @Synchronized
    fun reset() {
        lastAdmittedNanos = null
    }

    private companion object {
        fun checkFps(value: Double): Double {
            require(value > 0.0 && value.isFinite()) { "fps must be positive: $value" }
            return value
        }
    }
}
