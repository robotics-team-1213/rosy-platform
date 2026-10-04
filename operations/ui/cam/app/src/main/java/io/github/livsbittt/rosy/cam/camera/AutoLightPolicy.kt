package io.github.livsbittt.rosy.cam.camera

/** Pure, monotonic-clock policy for bounded automatic camera illumination. */
class AutoLightPolicy {
    private var lastMs = 0L
    private var darkSince: Long? = null
    private var onSince: Long? = null
    private var cooldownSince: Long? = null
    private var awaitingOff = false

    @Synchronized
    fun reset(nowMs: Long = 0) {
        lastMs = nowMs.coerceAtLeast(0)
        darkSince = null
        onSince = null
        cooldownSince = null
        awaitingOff = false
    }

    @Synchronized
    fun update(luma: Int, nowMs: Long, enabled: Boolean, supported: Boolean,
               thermalBlocked: Boolean, torchOn: Boolean): Boolean {
        if (nowMs < lastMs || nowMs < 0) {
            reset(nowMs)
            awaitingOff = torchOn
            return false
        }
        lastMs = nowMs
        if (!enabled || !supported || thermalBlocked || luma !in 0..255) {
            if (onSince != null) cooldownSince = nowMs
            onSince = null
            darkSince = null
            awaitingOff = awaitingOff || torchOn
            return false
        }
        if (awaitingOff) {
            darkSince = null
            if (torchOn) return false
            awaitingOff = false
        }
        cooldownSince?.let { start ->
            darkSince = null
            if (nowMs - start < COOLDOWN_MS) return false
            cooldownSince = null
        }
        // An already lit frame cannot tell us ambient brightness. Bound it too.
        if (onSince == null && torchOn) onSince = nowMs
        onSince?.let { start ->
            darkSince = null
            if (nowMs - start < MAX_ON_MS) return true
            onSince = null
            cooldownSince = nowMs
            awaitingOff = torchOn
            return false
        }
        if (luma > DARK_LUMA) {
            darkSince = null
            return false
        }
        val start = darkSince ?: nowMs.also { darkSince = it }
        if (nowMs - start < DARK_MS) return false
        darkSince = null
        onSince = nowMs
        return true
    }

    private companion object {
        const val DARK_LUMA = 28
        const val DARK_MS = 2000L
        const val MAX_ON_MS = 30000L
        const val COOLDOWN_MS = 10000L
    }
}
