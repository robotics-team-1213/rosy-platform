package io.github.livsbittt.rosy.overhead.link

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
        /** Same values as vectors.json `config_default`; used until the adapter's first `config`. */
        val DEFAULT = OverheadConfig(fps = 3.0, width = 1280, jpegQuality = 70, maxBytes = 200_000)
    }
}

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
    data class Unknown(val type: String) : ServerMessage
    data class Invalid(val reason: String) : ServerMessage
}

/** rosy-overhead/1 text messages (design section 3). Uses org.json, which Android ships. */
object Protocol {
    const val PROTO = "rosy-overhead/1"
    const val WS_PATH = "/overhead/v1/frames"
    const val CLOSE_BAD_PROTO = 4400
    const val CLOSE_UNAUTHORIZED = 4401
    const val CLOSE_REPLACED = 4409

    fun hello(
        source: String,
        appVersion: String,
        device: String,
        sensorWidth: Int,
        sensorHeight: Int,
        rotationDeg: Int,
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
        .toString()

    fun parseServerMessage(text: String): ServerMessage {
        val obj = try {
            JSONObject(text)
        } catch (e: JSONException) {
            return ServerMessage.Invalid("json")
        }
        return when (val type = obj.optString("type")) {
            "config" -> parseConfig(obj)
            "status" -> parseStatus(obj)
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

    /** Integer field that must be a whole number; null when missing or fractional. */
    private fun intField(obj: JSONObject, key: String): Int? {
        if (!obj.has(key) || obj.get(key) is JSONArray) return null
        val d = obj.optDouble(key, Double.NaN)
        if (d.isNaN() || d != Math.floor(d) || d > Int.MAX_VALUE || d < Int.MIN_VALUE) return null
        return d.toInt()
    }
}
