package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.Vectors
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** D-589 5: `camera` (down) and `camera_state` (up) against the shared vectors. */
class CameraProtocolTest {
    private val messages = Vectors.root.getJSONObject("messages")
    private val example = messages.getJSONObject("camera_example")

    @Test
    fun cameraVectorParses() {
        val msg = Protocol.parseServerMessage(example.toString())
        assertEquals(
            ServerMessage.Camera(
                seq = example.getLong("seq"),
                ev = example.getInt("ev"),
                aeLock = example.getBoolean("ae_lock"),
                awbLock = example.getBoolean("awb_lock"),
                maxExposureUs = example.getLong("max_exposure_us"),
                antibanding = example.getString("antibanding"),
            ),
            msg,
        )
    }

    @Test
    fun nullExposureCapAndExtraKeysAreAccepted() {
        val obj = JSONObject(example.toString()).put("max_exposure_us", JSONObject.NULL).put("future", 1)
        val msg = Protocol.parseServerMessage(obj.toString()) as ServerMessage.Camera
        assertEquals(null, msg.maxExposureUs)
    }

    @Test
    fun malformedCameraMessagesAreRejectedByField() {
        val cases = listOf(
            "seq" to JSONObject(example.toString()).put("seq", -1),
            "seq" to JSONObject(example.toString()).apply { remove("seq") },
            "ev" to JSONObject(example.toString()).put("ev", 1.5),
            "ev" to JSONObject(example.toString()).put("ev", "-1"),
            "ev" to JSONObject(example.toString()).put("ev", JSONObject.NULL),
            "ae_lock" to JSONObject(example.toString()).put("ae_lock", "true"),
            "ae_lock" to JSONObject(example.toString()).put("ae_lock", 1),
            "awb_lock" to JSONObject(example.toString()).apply { remove("awb_lock") },
            "max_exposure_us" to JSONObject(example.toString()).apply { remove("max_exposure_us") },
            "max_exposure_us" to JSONObject(example.toString()).put("max_exposure_us", 0),
            "max_exposure_us" to JSONObject(example.toString()).put("max_exposure_us", "8333"),
            "antibanding" to JSONObject(example.toString()).put("antibanding", "50hz"),
            "antibanding" to JSONObject(example.toString()).put("antibanding", "60HZ"),
        )
        for ((field, obj) in cases) {
            assertEquals(obj.toString(), ServerMessage.BadCamera(field), Protocol.parseServerMessage(obj.toString()))
        }
    }

    @Test
    fun cameraStateMatchesVector() {
        val expected = messages.getJSONObject("camera_state_example")
        val a = expected.getJSONObject("applied")
        val s = expected.getJSONObject("supported")
        val json = Protocol.cameraState(
            seq = expected.getLong("seq"),
            applied = CameraApplied(a.getInt("ev"), a.getBoolean("ae_lock"), a.getBoolean("awb_lock"),
                a.getLong("max_exposure_us"), a.getString("antibanding"), a.getString("mode")),
            supported = CameraSupported(s.getInt("ev_min"), s.getInt("ev_max"), s.getDouble("ev_step"),
                s.getBoolean("ae_lock"), s.getBoolean("awb_lock"), s.getLong("max_exposure_us"), s.getBoolean("antibanding_60hz")),
            exposureUs = expected.getLong("exposure_us"),
            iso = expected.getInt("iso"),
            thermal = expected.getInt("thermal"),
        )
        assertTrue(json, expected.similar(JSONObject(json)))
    }

    @Test
    fun unknownValuesGoOutAsJsonNull() {
        val json = JSONObject(Protocol.cameraState(0, CameraApplied(0, false, false, null, "auto", "local"),
            CameraSupported(0, 0, 0.0, false, false, null, false), null, null, -1))
        assertTrue(json.isNull("exposure_us"))
        assertTrue(json.isNull("iso"))
        assertTrue(json.getJSONObject("applied").isNull("max_exposure_us"))
        assertTrue(json.getJSONObject("supported").isNull("max_exposure_us"))
        assertEquals(-1, json.getInt("thermal"))
    }
}
