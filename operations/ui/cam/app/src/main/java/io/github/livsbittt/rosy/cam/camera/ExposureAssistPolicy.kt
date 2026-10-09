package io.github.livsbittt.rosy.cam.camera

/** D-544: current verdict; the only thing the policy may act on is the AE compensation index. */
enum class ExposureVerdict { OK, OVER, UNDER }

/**
 * Pure, monotonic-clock policy for a bounded AE exposure-compensation nudge (D-544 3, 5).
 * Hysteresis on the verdict, a dwell before each step, a minimum gap between steps, and a hard
 * +/-[limitIndex] bound. No timed return to 0: only a disabled [update] (or [reset]) returns it,
 * because undoing a correction that made the scene fine would make it bad again.
 */
class ExposureAssistPolicy(private val stepIndex: Int, private val limitIndex: Int) {
    var verdict = ExposureVerdict.OK
        private set
    var index = 0
        private set
    private var lastMs = 0L
    private var badSince: Long? = null
    private var lastMoveMs: Long? = null

    @Synchronized
    fun reset(nowMs: Long = 0) {
        verdict = ExposureVerdict.OK
        index = 0
        lastMs = nowMs.coerceAtLeast(0)
        badSince = null
        lastMoveMs = null
    }

    /** Returns the compensation index to apply now. [stats] null (stale or unreadable) holds the index. */
    @Synchronized
    fun update(stats: LumaStats?, nowMs: Long, enabled: Boolean, blocked: Boolean): Int {
        if (nowMs < lastMs || nowMs < 0) {
            reset(nowMs)
            return 0
        }
        lastMs = nowMs
        if (!enabled) {
            reset(nowMs)
            return 0
        }
        if (blocked || stats == null) {
            badSince = null
            return index
        }
        verdict = next(verdict, stats)
        if (verdict == ExposureVerdict.OK) {
            badSince = null
            return index
        }
        val since = badSince ?: nowMs.also { badSince = it }
        val gapOk = lastMoveMs?.let { nowMs - it >= MIN_INTERVAL_MS } ?: true
        if (nowMs - since >= DWELL_MS && gapOk) {
            val delta = if (verdict == ExposureVerdict.OVER) -stepIndex else stepIndex
            val target = (index + delta).coerceIn(-limitIndex, limitIndex)
            if (target != index) {
                index = target
                lastMoveMs = nowMs
            }
            badSince = nowMs
        }
        return index
    }

    private fun next(v: ExposureVerdict, s: LumaStats) = when (v) {
        ExposureVerdict.OK -> when {
            s.clip >= OVER_ON -> ExposureVerdict.OVER
            s.mean <= UNDER_MEAN_ON || s.crush >= UNDER_CRUSH_ON -> ExposureVerdict.UNDER
            else -> v
        }
        ExposureVerdict.OVER -> if (s.clip <= OVER_OFF) ExposureVerdict.OK else v
        ExposureVerdict.UNDER ->
            if (s.mean >= UNDER_MEAN_OFF && s.crush <= UNDER_CRUSH_OFF) ExposureVerdict.OK else v
    }

    companion object {
        const val OVER_ON = 0.25
        const val OVER_OFF = 0.10
        const val UNDER_MEAN_ON = 40.0
        const val UNDER_MEAN_OFF = 60.0
        const val UNDER_CRUSH_ON = 0.40
        const val UNDER_CRUSH_OFF = 0.20
        const val DWELL_MS = 3000L
        const val MIN_INTERVAL_MS = 4000L
        const val STEP_EV = 0.5
        const val LIMIT_EV = 1.5
    }
}

/** Shown on the stream screen (D-544 4). */
data class ExposureStatus(
    val supported: Boolean = false,
    val enabled: Boolean = false,
    val verdict: ExposureVerdict = ExposureVerdict.OK,
    val index: Int = 0,
    val stats: LumaStats? = null,
)
