package io.github.livsbittt.rosy.cam.camera

import io.github.livsbittt.rosy.cam.link.HelloLens
import kotlin.math.atan
import kotlin.math.max

/**
 * Lens setting: the default back camera, or the widest one. STANDARD is the default (2026-09-30
 * bench, tilted ceiling mount: STANDARD covered 99% of the track at ~420 px/m, WIDE 100% at only
 * ~196 px/m); WIDE is opt-in for mounts where the field does not fit.
 */
enum class LensChoice(val wire: String) {
    STANDARD("standard"),
    WIDE("wide"),
    ;

    companion object {
        val DEFAULT = STANDARD

        fun fromWire(value: String?): LensChoice? = entries.firstOrNull { it.wire == value }

        /** The saved setting, or [DEFAULT] when nothing is saved (fresh or pre-lens installs). */
        fun orDefault(saved: LensChoice?): LensChoice = saved ?: DEFAULT
    }
}

/**
 * One back camera as CameraX lists it, reduced to the facts lens selection needs.
 * [focalLengthsMm] is `LENS_INFO_AVAILABLE_FOCAL_LENGTHS`; the sensor size is
 * `SENSOR_INFO_PHYSICAL_SIZE` in mm (null when the camera does not report it).
 */
data class LensCandidate(
    val id: String,
    val focalLengthsMm: List<Float>,
    val sensorWidthMm: Float?,
    val sensorHeightMm: Float?,
    val logical: Boolean,
) {
    /**
     * A logical multi-camera that lists several focal lengths switches physical lenses itself,
     * so the focal length and FOV of the frames are not known.
     */
    val uncertain: Boolean get() = logical && focalLengthsMm.size > 1

    /** Shortest focal length the lens reports; null when it reports none. */
    val focalMm: Float? get() = focalLengthsMm.filter { it > 0f }.minOrNull()

    /** Horizontal field of view in degrees over the sensor's long edge; null without focal or sensor size. */
    val hfovDeg: Double? get() {
        val f = focalMm ?: return null
        val w = sensorWidthMm ?: return null
        val h = sensorHeightMm ?: return null
        val longEdge = max(w, h)
        if (longEdge <= 0f) return null
        return Math.toDegrees(2.0 * atan(longEdge / (2.0 * f)))
    }
}

/** The camera to bind. [fellBack] is true when WIDE was asked for but no wider back camera exists. */
data class LensPick(
    val camera: LensCandidate,
    val kind: LensChoice,
    val fellBack: Boolean,
)

/**
 * Picks the camera for a [LensChoice] from the back cameras, in CameraX order.
 *
 * - STANDARD is the first back camera, which is what `CameraSelector.DEFAULT_BACK_CAMERA` binds.
 * - WIDE is the back camera with the widest horizontal FOV (shortest focal length when the
 *   sensor size is missing), preferring a physical camera over a logical multi-camera. It must be
 *   wider than STANDARD by more than [MIN_WIDER_DEG]; otherwise WIDE falls back to STANDARD.
 *
 * `setZoomRatio(0.5)` is not used: phones such as the Galaxy S21 expose the ultra-wide as its own
 * camera id and keep the main camera's zoom range at 1x and above.
 */
object LensSelector {
    /** A lens is only "wider" when it gains more than this; equal lenses on different ids do not count. */
    const val MIN_WIDER_DEG = 3.0

    fun pick(backCameras: List<LensCandidate>, choice: LensChoice): LensPick? {
        val standard = backCameras.firstOrNull() ?: return null
        if (choice == LensChoice.STANDARD) return LensPick(standard, LensChoice.STANDARD, fellBack = false)
        val wide = widest(backCameras, standard)
            ?: return LensPick(standard, LensChoice.STANDARD, fellBack = true)
        return LensPick(wide, LensChoice.WIDE, fellBack = false)
    }

    /** The optional hello.lens for [pick]; null when its focal length or FOV is unknown or uncertain. */
    fun helloLens(pick: LensPick?): HelloLens? {
        val camera = pick?.camera ?: return null
        if (camera.uncertain) return null
        val focal = camera.focalMm ?: return null
        val hfov = camera.hfovDeg ?: return null
        return HelloLens(pick.kind.wire, focal.toDouble(), hfov)
    }

    /** True when some back camera is wider than the default one. */
    fun hasWide(backCameras: List<LensCandidate>): Boolean =
        backCameras.firstOrNull()?.let { widest(backCameras, it) } != null

    private fun widest(cameras: List<LensCandidate>, standard: LensCandidate): LensCandidate? {
        val wider = cameras.filter { it !== standard && isWider(it, standard) }
        val pool = wider.filter { !it.logical }.ifEmpty { wider }
        return pool.maxWithOrNull(
            compareBy<LensCandidate>({ it.hfovDeg ?: Double.NEGATIVE_INFINITY }, { -(it.focalMm ?: Float.MAX_VALUE) }),
        )
    }

    private fun isWider(candidate: LensCandidate, standard: LensCandidate): Boolean {
        val a = candidate.hfovDeg
        val b = standard.hfovDeg
        if (a != null && b != null) return a - b > MIN_WIDER_DEG
        // No sensor size on one side: fall back to focal length alone.
        val fa = candidate.focalMm ?: return false
        val fb = standard.focalMm ?: return false
        return fa < fb * 0.9f
    }
}
