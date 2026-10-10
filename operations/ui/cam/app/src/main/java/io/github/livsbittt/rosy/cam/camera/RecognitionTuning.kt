package io.github.livsbittt.rosy.cam.camera

import io.github.livsbittt.rosy.cam.link.CameraApplied
import io.github.livsbittt.rosy.cam.link.CameraSupported
import io.github.livsbittt.rosy.cam.link.ServerMessage
import kotlin.math.ceil
import kotlin.math.floor

/** A Camera2 `CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES` entry. */
data class FpsRange(val lower: Int, val upper: Int)

/** What the bound camera can do, read once per bind from Camera2 characteristics and CameraX exposure state. */
data class CameraCapabilities(
    /** Exposure-compensation index range; both 0 with [evStep] 0 when compensation is unsupported. */
    val evMin: Int = 0,
    val evMax: Int = 0,
    /** EV per index step (CameraX `exposureCompensationStep`). */
    val evStep: Double = 0.0,
    val aeLock: Boolean = false,
    val awbLock: Boolean = false,
    val antibanding60: Boolean = false,
    val fpsRanges: List<FpsRange> = emptyList(),
) {
    /** Ranges we may pick: a positive floor and no faster than [RecognitionTuning.MAX_SENSOR_FPS] (heat). */
    internal val capRanges: List<FpsRange>
        get() = fpsRanges.filter { it.lower >= 1 && it.lower <= it.upper && it.upper <= RecognitionTuning.MAX_SENSOR_FPS }

    fun supported() = CameraSupported(
        evMin, evMax, Math.round(evStep * 10_000) / 10_000.0, aeLock, awbLock,
        capRanges.maxOfOrNull { it.lower }?.let { capUs(FpsRange(it, it)) }, antibanding60,
    )
}

enum class Antibanding(val wire: String) { HZ60("60hz"), AUTO("auto") }

/**
 * What the phone writes: the exposure-compensation index through CameraX, the rest through Camera2 interop
 * capture-request options. Defaults are CameraX's own behaviour. Geometry (lens, zoom, focus, resolution) has no
 * field here on purpose (D-589 2).
 */
data class CameraSettings(
    val ev: Int = 0,
    val aeLock: Boolean = false,
    val awbLock: Boolean = false,
    /** AE target fps range whose floor bounds the frame duration and so the exposure time; null = CameraX's. */
    val fpsRange: FpsRange? = null,
    val antibanding: Antibanding = Antibanding.AUTO,
) {
    /** Longest exposure the AE can choose with [fpsRange] in force; null when not capped. */
    val maxExposureUs: Long? get() = fpsRange?.let(::capUs)
    val locked: Boolean get() = aeLock || awbLock

    fun applied(mode: TuningMode) = CameraApplied(ev, aeLock, awbLock, maxExposureUs, antibanding.wire, mode.wire)
}

/** Why the camera has its current settings; `camera_state.applied.mode` on the wire. */
enum class TuningMode(val wire: String) {
    /** A Vision `camera` message newer than [RecognitionTuning.VISION_FRESH_MS] rules. */
    VISION("vision"),

    /** No fresh Vision request: CameraX defaults, EV from the D-544 local assist when that switch is on. */
    LOCAL("local"),

    /**
     * The "인식 자동 노출 (Vision)" switch is off: `camera` messages are ignored and the camera returns to [LOCAL]
     * settings, also while the phone is hot (the operator's switch wins over the thermal hold).
     */
    DISABLED("disabled"),

    /** Switch on and thermal status SEVERE or worse: nothing changes, the last settings (locked or not) are kept. */
    THERMAL_HOLD("thermal_hold"),
}

internal fun capUs(range: FpsRange): Long = 1_000_000L / range.lower

/**
 * D-589 3, 7 precedence for the phone side, pure and clock-injected (milliseconds on a monotonic clock).
 * Order: settings switch off > thermal hold > fresh Vision request > local (D-544).
 * Not thread-safe; the camera controller calls it on the main thread.
 */
class RecognitionTuning(private val freshMs: Long = VISION_FRESH_MS) {
    var enabled = true
        private set

    /** PowerManager.THERMAL_STATUS_*, or -1 when unknown. */
    var thermal = -1

    /** `seq` of the last `camera` message seen, also when it was ignored; echoed in `camera_state`. */
    var lastSeq: Long? = null
        private set

    private var request: ServerMessage.Camera? = null
    private var receivedAtMs = 0L

    /** Newest request that came within [MIN_GAP_MS]; applied by [tick] when the gap ends. */
    private var pending: ServerMessage.Camera? = null

    /** Turning the switch off forgets the request, so a stale one never applies when it is turned on again. */
    fun setEnabled(on: Boolean) {
        enabled = on
        if (!on) {
            request = null
            pending = null
        }
    }

    enum class Receipt { APPLIED, IGNORED_SWITCH_OFF, TOO_SOON }

    /**
     * Records [msg]. One closer than [MIN_GAP_MS] to the previously applied request waits as [pending] (the newest
     * wins) and is applied by [tick], so a burst cannot make the camera hunt and the last word is never lost.
     * [lastSeq] follows applied and switch-off-ignored messages, not waiting ones.
     */
    fun receive(msg: ServerMessage.Camera, nowMs: Long): Receipt {
        if (!enabled) {
            lastSeq = msg.seq
            return Receipt.IGNORED_SWITCH_OFF
        }
        if (request != null && nowMs >= receivedAtMs && nowMs - receivedAtMs < MIN_GAP_MS) {
            pending = msg
            return Receipt.TOO_SOON
        }
        apply(msg, nowMs)
        return Receipt.APPLIED
    }

    /** Applies a [pending] request once the gap has passed; true when it did. Call on every evaluation. */
    fun tick(nowMs: Long): Boolean {
        val next = pending ?: return false
        if (nowMs >= receivedAtMs && nowMs - receivedAtMs < MIN_GAP_MS) return false
        apply(next, nowMs)
        return true
    }

    private fun apply(msg: ServerMessage.Camera, nowMs: Long) {
        lastSeq = msg.seq
        request = msg
        receivedAtMs = nowMs
        pending = null
    }

    fun mode(nowMs: Long): TuningMode = when {
        !enabled -> TuningMode.DISABLED
        thermal >= THERMAL_SEVERE -> TuningMode.THERMAL_HOLD
        fresh(nowMs) -> TuningMode.VISION
        else -> TuningMode.LOCAL
    }

    /**
     * The settings the camera should end up with in [mode]; [current] is what is written now. While the torch is
     * on, AE is never locked under Vision: a lock taken in torch light would stay wrong after it goes off.
     */
    fun target(
        mode: TuningMode,
        caps: CameraCapabilities,
        current: CameraSettings,
        localEv: Int,
        torchOn: Boolean = false,
    ): CameraSettings =
        when (mode) {
            TuningMode.THERMAL_HOLD -> current
            TuningMode.VISION -> request?.let { clamp(it, caps) }?.let { if (torchOn) it.copy(aeLock = false) else it }
                ?: CameraSettings(ev = localEv)
            TuningMode.LOCAL, TuningMode.DISABLED -> CameraSettings(ev = localEv)
        }

    /** A clock that went backwards makes the request stale rather than everlasting. */
    private fun fresh(nowMs: Long): Boolean = request != null && nowMs >= receivedAtMs && nowMs - receivedAtMs <= freshMs

    companion object {
        const val VISION_FRESH_MS = 60_000L

        /** AE/AWB locks wait this long after the exposure change is confirmed, so the AE converges first. */
        const val SETTLE_MS = 1_000L

        /** Locks go on after this long even without a confirmation (a failed or stalled control). */
        const val SETTLE_TIMEOUT_MS = 3_000L

        /** Requests closer together than this are dropped (still echoed). */
        const val MIN_GAP_MS = 500L

        /** D-589 2 allow-list bounds in real EV; the index bounds follow from the device's EV step. */
        const val EV_MIN = -2.0
        const val EV_MAX = 1.0

        /** Fps ranges above this are never chosen for the exposure cap: the sensor would run hotter for 3 fps. */
        const val MAX_SENSOR_FPS = 30

        /** PowerManager.THERMAL_STATUS_SEVERE. */
        const val THERMAL_SEVERE = 3

        /** Cuts [req] down to the allow-list and to what [caps] says the camera can do. */
        fun clamp(req: ServerMessage.Camera, caps: CameraCapabilities): CameraSettings {
            val evOk = caps.evStep > 0.0 && caps.evMin < caps.evMax
            val (lo, hi) = evIndexBounds(caps)
            return CameraSettings(
                ev = if (evOk && lo <= hi) req.ev.coerceIn(lo, hi) else 0,
                aeLock = req.aeLock && caps.aeLock,
                awbLock = req.awbLock && caps.awbLock,
                fpsRange = req.maxExposureUs?.let { pickRange(it, caps.capRanges) },
                antibanding = if (req.antibanding == Antibanding.HZ60.wire && caps.antibanding60) Antibanding.HZ60 else Antibanding.AUTO,
            )
        }

        /**
         * Index range for [EV_MIN]..[EV_MAX] EV at the device step (ceil / floor, with a small tolerance for
         * steps like 1/6 that are not exact in binary), intersected with the device range.
         */
        internal fun evIndexBounds(caps: CameraCapabilities): Pair<Int, Int> {
            if (caps.evStep <= 0.0) return 0 to 0
            val lo = ceil(EV_MIN / caps.evStep - 1e-9).toInt()
            val hi = floor(EV_MAX / caps.evStep + 1e-9).toInt()
            return maxOf(caps.evMin, lo) to minOf(caps.evMax, hi)
        }

        /**
         * With AE on, exposure time is bounded by the frame duration, i.e. 1 / range floor. Picks the lowest floor
         * whose reported cap ([capUs]) meets [maxUs], so a reported cap sent back unchanged picks the same range;
         * when none does, the highest floor (the closest cap the camera has).
         */
        internal fun pickRange(maxUs: Long, ranges: List<FpsRange>): FpsRange? {
            return ranges.filter { capUs(it) <= maxUs }.minWithOrNull(compareBy({ it.lower }, { it.upper }))
                ?: ranges.maxWithOrNull(compareBy({ it.lower }, { -it.upper }))
        }

        /** The part of the settings that changes the exposure and so must settle before a lock. */
        private fun exposureKey(s: CameraSettings) = Triple(s.ev, s.fpsRange, s.antibanding)

        /**
         * The step to write now toward [goal]. A change to EV, the exposure cap or anti-banding goes in with the
         * locks off. The locks follow once [confirmed] shows that change, at least one capture came after it
         * ([framed]) and [SETTLE_MS] has passed since it ([changedAtMs]; null = not started yet, e.g. no capture since
         * bind), or after [SETTLE_TIMEOUT_MS] with a capture in any case.
         *
         * "Confirmed" means the control call completed, i.e. the setting was applied to the repeating request. For
         * EV that is CameraX's own completion; for the fps range and anti-banding it says nothing about AE having
         * converged, which is what [SETTLE_MS] is for.
         */
        fun step(
            written: CameraSettings,
            confirmed: CameraSettings,
            goal: CameraSettings,
            changedAtMs: Long?,
            nowMs: Long,
            framed: Boolean = true,
        ): CameraSettings {
            // No early return for goal == written: a change the writer did not make (the torch) must unlock too.
            if (!goal.locked) return goal
            val unlocked = goal.copy(aeLock = false, awbLock = false)
            if (exposureKey(written) != exposureKey(goal)) return unlocked
            if (changedAtMs == null || !framed) return unlocked
            val since = (nowMs - changedAtMs).takeIf { it >= 0 } ?: Long.MAX_VALUE
            val confirmedAll = exposureKey(confirmed) == exposureKey(goal)
            return if ((confirmedAll && since >= SETTLE_MS) || since >= SETTLE_TIMEOUT_MS) goal else unlocked
        }
    }
}

/** One line on the stream screen (D-589 S2 4). [mode] null while no camera is bound. */
data class TuningStatus(
    val mode: TuningMode? = null,
    val applied: CameraSettings = CameraSettings(),
    val localAssist: Boolean = false,
    /** EV per index step of the bound camera, so the line shows real EV. */
    val evStep: Double = 0.0,
) {
    /** Real EV with one decimal and a real minus sign: "EV −1.0", "EV 0.0", "EV +0.5". */
    val evText: String get() {
        val ev = applied.ev * evStep
        val text = String.format(java.util.Locale.ROOT, "%.1f", kotlin.math.abs(ev))
        return "EV " + when {
            text == "0.0" -> text
            ev < 0 -> "−$text"
            else -> "+$text"
        }
    }
}
