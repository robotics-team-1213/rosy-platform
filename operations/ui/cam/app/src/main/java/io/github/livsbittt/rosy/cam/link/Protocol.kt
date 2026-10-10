package io.github.livsbittt.rosy.cam.link

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/** Stream parameters the adapter sends in `config`. The app follows them and never raises them itself. */
data class OverheadConfig(
    val fps: Double,
    val width: Int,
    val jpegQuality: Int,
    val maxBytes: Int,
) {
    /** 16:9 target height for [width], rounded to an even number for YUV subsampling. */
    val height: Int get() = ((width * 9 / 16) + 1) and 1.inv()

    companion object {
        /** Same values as overhead-ingest.v1.json `config_default`; used until the adapter's first `config`. */
        val DEFAULT = OverheadConfig(fps = 3.0, width = 1280, jpegQuality = 70, maxBytes = 200_000)
    }
}

/**
 * Optional additive `hello.lens` (2026-09-30): which lens the frames come from, for a later
 * calibration choice. Receivers ignore unknown hello fields, so older ones just skip it.
 * [focalMm] and [hfovDeg] go on the wire rounded to 0.1.
 */
data class HelloLens(val kind: String, val focalMm: Double, val hfovDeg: Double)

/** Text messages from the adapter. */
sealed interface ServerMessage {
    data class Config(val config: OverheadConfig) : ServerMessage
    data class Status(
        val cornersSeen: List<Int>,
        val cornersNeeded: Int,
        val robotsSeen: List<String>,
        val rxFps: Double,
        val dropped: Long,
    ) : ServerMessage

    /**
     * D-589 5: Vision asks for these camera settings. The phone clamps them to its allow-list and the device
     * ([io.github.livsbittt.rosy.cam.camera.RecognitionTuning]); [antibanding] is "60hz" or "auto".
     */
    data class Camera(
        val seq: Long,
        val ev: Int,
        val aeLock: Boolean,
        val awbLock: Boolean,
        val maxExposureUs: Long?,
        val antibanding: String,
    ) : ServerMessage

    /** A `camera` message that failed strict parsing; logged and ignored, never a link error. */
    data class BadCamera(val reason: String) : ServerMessage
    data class Unknown(val type: String) : ServerMessage
    data class Invalid(val reason: String) : ServerMessage
}

/** D-589 5: `camera_state.applied`, the settings the camera really runs with, and why ([mode]). */
data class CameraApplied(
    val ev: Int,
    val aeLock: Boolean,
    val awbLock: Boolean,
    val maxExposureUs: Long?,
    val antibanding: String,
    val mode: String,
)

/** D-589 5: `camera_state.supported`, what this camera can do. [maxExposureUs] is the shortest reachable cap. */
data class CameraSupported(
    val evMin: Int,
    val evMax: Int,
    val evStep: Double,
    val aeLock: Boolean,
    val awbLock: Boolean,
    val maxExposureUs: Long?,
    val antibanding60hz: Boolean,
)

/** rosy-overhead/1 text messages (design section 3). Uses org.json, which Android ships. */
object Protocol {
    const val PROTO = "rosy-overhead/1"
    const val WS_PATH = "/overhead/v1/frames"
    const val CLOSE_BAD_PROTO = 4400
    const val CLOSE_UNAUTHORIZED = 4401
    const val CLOSE_REPLACED = 4409

    /** D-341 11: the credential is valid but not allowed (this source, this site). Final: retry cannot help. */
    const val CLOSE_FORBIDDEN = 4403

    /** RFC 6455 "Try Again Later": the receiver is overloaded; always retryable. */
    const val CLOSE_TRY_AGAIN = 1013

    /** D-341 11: the receiver cannot tell whether the credential is valid (e.g. Fleet down); retryable, not an auth failure. */
    const val CLOSE_CREDENTIAL_UNKNOWN = 4503

    // Transition exception, remove one release after every site runs 1013 receivers (D-341 §11).
    // Equal to failure-classes.v1.json close_4400_retry_reasons (FailureClassTest asserts it).
    internal val TRANSIENT_4400 = setOf("", "no hello")

    /**
     * Close 4400 is an incompatibility (wrong `proto`, hello schema) for every reason except exactly
     * "" or "no hello" (trimmed, case-insensitive), which pre-1013 receivers sent when their hello timer
     * fired; those retry. Validation messages never match. Shared cases: vectors `close_4400_reasons`.
     */
    fun isIncompatibleClose(code: Int, reason: String): Boolean =
        code == CLOSE_BAD_PROTO && reason.trim().lowercase() !in TRANSIENT_4400

    fun hello(
        source: String,
        appVersion: String,
        device: String,
        sensorWidth: Int,
        sensorHeight: Int,
        rotationDeg: Int,
        lens: HelloLens? = null,
    ): String = JSONObject()
        .put("type", "hello")
        .put("proto", PROTO)
        .put("source", source)
        .put("app_version", appVersion)
        .put("device", device)
        .put(
            "sensor",
            JSONObject()
                .put("width", sensorWidth)
                .put("height", sensorHeight)
                .put("rotation_deg", rotationDeg),
        )
        .apply {
            if (lens != null) {
                put(
                    "lens",
                    JSONObject()
                        .put("kind", lens.kind)
                        .put("focal_mm", round1(lens.focalMm))
                        .put("hfov_deg", round1(lens.hfovDeg)),
                )
            }
        }
        .toString()

    private fun round1(value: Double): Double = Math.round(value * 10.0) / 10.0

    fun parseServerMessage(text: String): ServerMessage {
        val obj = try {
            JSONObject(text)
        } catch (e: JSONException) {
            return ServerMessage.Invalid("json")
        }
        return when (val type = obj.optString("type")) {
            "config" -> parseConfig(obj)
            "status" -> parseStatus(obj)
            "camera" -> parseCamera(obj)
            else -> ServerMessage.Unknown(type)
        }
    }

    private fun parseConfig(obj: JSONObject): ServerMessage {
        val fps = obj.optDouble("fps", Double.NaN)
        if (fps.isNaN() || fps <= 0.0) return ServerMessage.Invalid("fps")
        val width = intField(obj, "width") ?: return ServerMessage.Invalid("width")
        if (width !in 16..0xFFFF) return ServerMessage.Invalid("width")
        val quality = intField(obj, "jpeg_quality") ?: return ServerMessage.Invalid("jpeg_quality")
        if (quality !in 1..100) return ServerMessage.Invalid("jpeg_quality")
        val maxBytes = intField(obj, "max_bytes") ?: return ServerMessage.Invalid("max_bytes")
        if (maxBytes <= 0) return ServerMessage.Invalid("max_bytes")
        return ServerMessage.Config(OverheadConfig(fps, width, quality, maxBytes))
    }

    private fun parseStatus(obj: JSONObject): ServerMessage = try {
        ServerMessage.Status(
            cornersSeen = obj.getJSONArray("corners_seen").let { a -> List(a.length()) { a.getInt(it) } },
            cornersNeeded = obj.getInt("corners_needed"),
            robotsSeen = obj.getJSONArray("robots_seen").let { a -> List(a.length()) { a.getString(it) } },
            rxFps = obj.getDouble("rx_fps"),
            dropped = obj.getLong("dropped"),
        )
    } catch (e: JSONException) {
        ServerMessage.Invalid("status")
    }

    /**
     * D-589 5, strict: every key present, booleans as JSON booleans, whole JSON numbers, `max_exposure_us` a
     * positive number or null, `antibanding` "60hz" or "auto". Extra keys are ignored.
     */
    private fun parseCamera(obj: JSONObject): ServerMessage {
        val seq = wholeNumber(obj, "seq")?.takeIf { it >= 0 } ?: return ServerMessage.BadCamera("seq")
        val ev = wholeNumber(obj, "ev")?.takeIf { it in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong() }?.toInt()
            ?: return ServerMessage.BadCamera("ev")
        val aeLock = obj.opt("ae_lock") as? Boolean ?: return ServerMessage.BadCamera("ae_lock")
        val awbLock = obj.opt("awb_lock") as? Boolean ?: return ServerMessage.BadCamera("awb_lock")
        if (!obj.has("max_exposure_us")) return ServerMessage.BadCamera("max_exposure_us")
        val maxExposureUs = if (obj.isNull("max_exposure_us")) null else
            wholeNumber(obj, "max_exposure_us")?.takeIf { it > 0 } ?: return ServerMessage.BadCamera("max_exposure_us")
        val antibanding = (obj.opt("antibanding") as? String)?.takeIf { it in ANTIBANDING }
            ?: return ServerMessage.BadCamera("antibanding")
        return ServerMessage.Camera(seq, ev, aeLock, awbLock, maxExposureUs, antibanding)
    }

    private val ANTIBANDING = setOf("60hz", "auto")

    /** A JSON number (never a numeric string) with no fraction; null otherwise. */
    private fun wholeNumber(obj: JSONObject, key: String): Long? {
        val n = obj.opt(key) as? Number ?: return null
        val d = n.toDouble()
        if (d.isNaN() || d != Math.floor(d) || Math.abs(d) > 9.0e15) return null
        return d.toLong()
    }

    /** D-589 5: uplink `camera_state`; [thermal] is PowerManager.THERMAL_STATUS_* or -1. */
    fun cameraState(
        seq: Long,
        applied: CameraApplied,
        supported: CameraSupported,
        exposureUs: Long?,
        iso: Int?,
        thermal: Int,
    ): String = JSONObject()
        .put("type", "camera_state")
        .put("seq", seq)
        .put(
            "applied",
            JSONObject()
                .put("ev", applied.ev)
                .put("ae_lock", applied.aeLock)
                .put("awb_lock", applied.awbLock)
                .put("max_exposure_us", applied.maxExposureUs ?: JSONObject.NULL)
                .put("antibanding", applied.antibanding)
                .put("mode", applied.mode),
        )
        .put(
            "supported",
            JSONObject()
                .put("ev_min", supported.evMin)
                .put("ev_max", supported.evMax)
                .put("ev_step", supported.evStep)
                .put("ae_lock", supported.aeLock)
                .put("awb_lock", supported.awbLock)
                .put("max_exposure_us", supported.maxExposureUs ?: JSONObject.NULL)
                .put("antibanding_60hz", supported.antibanding60hz),
        )
        .put("exposure_us", exposureUs ?: JSONObject.NULL)
        .put("iso", iso ?: JSONObject.NULL)
        .put("thermal", thermal)
        .toString()

    /** Integer field that must be a whole number; null when missing or fractional. */
    private fun intField(obj: JSONObject, key: String): Int? {
        if (!obj.has(key) || obj.get(key) is JSONArray) return null
        val d = obj.optDouble(key, Double.NaN)
        if (d.isNaN() || d != Math.floor(d) || d > Int.MAX_VALUE || d < Int.MIN_VALUE) return null
        return d.toInt()
    }
}
