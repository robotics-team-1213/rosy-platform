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

    /** The "인식 자동 노출 (Vision)" switch is off: `camera` messages are ignored; otherwise as [LOCAL]. */
    DISABLED("disabled"),

    /** Thermal status SEVERE or worse: nothing changes, the last settings (locked or not) are kept. */
    THERMAL_HOLD("thermal_hold"),
}

internal fun capUs(range: FpsRange): Long = 1_000_000L / range.lower

/**
 * D-589 3, 7 precedence for the phone side, pure and clock-injected (milliseconds on a monotonic clock).
 * Order: thermal hold > settings switch off > fresh Vision request > local (D-544).
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

    /** Turning the switch off forgets the request, so a stale one never applies when it is turned on again. */
    fun setEnabled(on: Boolean) {
        enabled = on
        if (!on) request = null
    }

    /** Records [msg]. Returns false when the switch is off and the message is ignored. */
    fun receive(msg: ServerMessage.Camera, nowMs: Long): Boolean {
        lastSeq = msg.seq
        if (!enabled) return false
        request = msg
        receivedAtMs = nowMs
        return true
    }

    fun mode(nowMs: Long): TuningMode = when {
        thermal >= THERMAL_SEVERE -> TuningMode.THERMAL_HOLD
        !enabled -> TuningMode.DISABLED
        fresh(nowMs) -> TuningMode.VISION
        else -> TuningMode.LOCAL
    }

    /** The settings the camera should end up with in [mode]; [current] is what is written now. */
    fun target(mode: TuningMode, caps: CameraCapabilities, current: CameraSettings, localEv: Int): CameraSettings =
        when (mode) {
            TuningMode.THERMAL_HOLD -> current
            TuningMode.VISION -> request?.let { clamp(it, caps) } ?: CameraSettings(ev = localEv)
            TuningMode.LOCAL, TuningMode.DISABLED -> CameraSettings(ev = localEv)
        }

    /** A clock that went backwards makes the request stale rather than everlasting. */
    private fun fresh(nowMs: Long): Boolean = request != null && nowMs >= receivedAtMs && nowMs - receivedAtMs <= freshMs

    companion object {
        const val VISION_FRESH_MS = 60_000L

        /** AE/AWB locks wait this long after an EV write so the AE converges on the new EV before freezing. */
        const val SETTLE_MS = 1_000L

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
         * that meets [maxUs]; when none does, the highest floor (the closest cap the camera has).
         */
        internal fun pickRange(maxUs: Long, ranges: List<FpsRange>): FpsRange? {
            val need = ceil(1_000_000.0 / maxUs).toInt()
            return ranges.filter { it.lower >= need }.minWithOrNull(compareBy({ it.lower }, { it.upper }))
                ?: ranges.maxWithOrNull(compareBy({ it.lower }, { -it.upper }))
        }

        /**
         * The step to write now toward [target]: an EV change goes in with the locks off, and the locks follow
         * [SETTLE_MS] after the last EV write ([evChangedAtMs]).
         */
        fun step(written: CameraSettings, target: CameraSettings, evChangedAtMs: Long?, nowMs: Long): CameraSettings {
            if (target == written || !target.locked) return target
            val settling = target.ev != written.ev ||
                (evChangedAtMs != null && nowMs >= evChangedAtMs && nowMs - evChangedAtMs < SETTLE_MS)
            return if (settling) target.copy(aeLock = false, awbLock = false) else target
        }
    }
}

/** One line on the stream screen (D-589 S2 4). [mode] null while no camera is bound. */
data class TuningStatus(
    val mode: TuningMode? = null,
    val applied: CameraSettings = CameraSettings(),
    val localAssist: Boolean = false,
) {
    /** "EV −1", "EV 0", "EV +2" with a real minus sign. */
    val evText: String get() = "EV " + when {
        applied.ev < 0 -> "−${-applied.ev}"
        applied.ev > 0 -> "+${applied.ev}"
        else -> "0"
    }
}
