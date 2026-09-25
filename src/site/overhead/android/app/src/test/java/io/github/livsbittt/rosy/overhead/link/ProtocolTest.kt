package io.github.livsbittt.rosy.overhead.link

import io.github.livsbittt.rosy.overhead.Vectors
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolTest {
    private val messages = Vectors.root.getJSONObject("messages")

    @Test
    fun protoNameAndPathMatchVectors() {
        assertEquals(Vectors.root.getString("proto"), Protocol.PROTO)
        assertEquals(Vectors.root.getString("ws_path"), Protocol.WS_PATH)
    }

    @Test
    fun closeCodesMatchVectors() {
        val codes = Vectors.root.getJSONObject("close_codes")
        assertEquals(codes.getInt("bad_proto"), Protocol.CLOSE_BAD_PROTO)
        assertEquals(codes.getInt("unauthorized_source"), Protocol.CLOSE_UNAUTHORIZED)
        assertEquals(codes.getInt("replaced_by_same_source"), Protocol.CLOSE_REPLACED)
    }

    @Test
    fun helloMatchesValidVector() {
        val hello = Protocol.hello(
            source = "overhead-1",
            appVersion = "0.1.0",
            device = "test-device",
            sensorWidth = 1280,
            sensorHeight = 720,
            rotationDeg = 90,
        )
        val expected = messages.getJSONObject("hello_valid")
        assertTrue("hello=$hello", expected.similar(JSONObject(hello)))
    }

    @Test
    fun helloDoesNotMatchBadProtoVector() {
        val hello = Protocol.hello("overhead-1", "0.1.0", "test-device", 1280, 720, 90)
        val badProto = messages.getJSONObject("hello_bad_proto")
        assertTrue(!badProto.similar(JSONObject(hello)))
    }

    @Test
    fun parsesDefaultConfigAsTheBuiltInDefault() {
        val parsed = Protocol.parseServerMessage(messages.getJSONObject("config_default").toString())
        assertEquals(
            ServerMessage.Config(OverheadConfig(fps = 3.0, width = 1280, jpegQuality = 70, maxBytes = 200_000)),
            parsed,
        )
        assertEquals(ServerMessage.Config(OverheadConfig.DEFAULT), parsed)
    }

    @Test
    fun parsesStatusExample() {
        val parsed = Protocol.parseServerMessage(messages.getJSONObject("status_example").toString())
        assertEquals(
            ServerMessage.Status(
                cornersSeen = listOf(30, 31, 33),
                cornersNeeded = 4,
                robotsSeen = listOf("rosy_01"),
                rxFps = 2.9,
                dropped = 0,
            ),
            parsed,
        )
    }

    @Test
    fun rejectsConfigWithOutOfRangeValues() {
        val base = messages.getJSONObject("config_default")
        val cases = listOf("fps" to 0, "width" to 0, "jpeg_quality" to 101, "jpeg_quality" to 0, "max_bytes" to 0)
        for ((key, bad) in cases) {
            val msg = JSONObject(base.toString()).put(key, bad)
            assertEquals("$key=$bad", ServerMessage.Invalid(key), Protocol.parseServerMessage(msg.toString()))
        }
    }

    @Test
    fun rejectsConfigWithMissingField() {
        val msg = JSONObject(messages.getJSONObject("config_default").toString())
        msg.remove("max_bytes")
        assertEquals(ServerMessage.Invalid("max_bytes"), Protocol.parseServerMessage(msg.toString()))
    }

    @Test
    fun acceptsFractionalFps() {
        val msg = JSONObject(messages.getJSONObject("config_default").toString()).put("fps", 1.5)
        val parsed = Protocol.parseServerMessage(msg.toString()) as ServerMessage.Config
        assertEquals(1.5, parsed.config.fps, 0.0)
    }

    @Test
    fun unknownTypeIsReportedNotThrown() {
        assertEquals(ServerMessage.Unknown("pong"), Protocol.parseServerMessage("{\"type\":\"pong\"}"))
    }

    @Test
    fun malformedJsonIsInvalid() {
        assertEquals(ServerMessage.Invalid("json"), Protocol.parseServerMessage("not json"))
    }
}
