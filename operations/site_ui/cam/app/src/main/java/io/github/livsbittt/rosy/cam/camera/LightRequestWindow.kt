package io.github.livsbittt.rosy.cam.camera

/** An explicit, non-renewing light request; expiry never starts another request. */
class LightRequestWindow {
    private var startedMs: Long? = null

    fun start(nowMs: Long) {
        if (startedMs == null) startedMs = nowMs
    }

    fun active(nowMs: Long): Boolean {
        val started = startedMs ?: return false
        if (nowMs - started !in 0 until DURATION_MS) {
            cancel()
            return false
        }
        return true
    }

    fun cancel() { startedMs = null }

    companion object { const val DURATION_MS = 30_000L }
}
