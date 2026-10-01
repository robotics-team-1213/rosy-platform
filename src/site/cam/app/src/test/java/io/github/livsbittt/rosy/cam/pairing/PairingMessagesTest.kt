package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.pairing.PairingVectorsTest.Companion.expectedReason
import io.github.livsbittt.rosy.cam.pairing.PairingVectorsTest.Companion.objects
import io.github.livsbittt.rosy.cam.pairing.PairingVectorsTest.Companion.vector
import java.nio.charset.StandardCharsets.UTF_8
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** D-341 request/reveal/result shapes against every vector case, plus the S2 reply shapes (create, poll, confirm). */
class PairingMessagesTest {
    private fun failures(listName: String, check: (JSONObject) -> String?): List<String> {
        val cases = vector.getJSONArray(listName).objects()
        assertTrue("no $listName", cases.isNotEmpty())
        return cases.mapNotNull { case ->
            val want = case.expectedReason()
            val got = check(case)
            if (got == want) null else "${case.getString("id")}: expected ${want ?: "valid"}, got ${got ?: "valid"}"
        }
    }

    /** pairing.py's test measures the compact UTF-8 JSON (`separators=(",", ":")`); org.json writes it compact. */
    private fun compact(case: JSONObject): ByteArray = case.get("body").toString().toByteArray(UTF_8)

    @Test
    fun everyRequestCase() {
        val failed = failures("request_cases") { PairingRequest.validate(compact(it)) }
        assertTrue(failed.joinToString("\n"), failed.isEmpty())
    }

    @Test
    fun everyRevealCase() {
        val failed = failures("reveal_cases") { PairingReveal.validate(compact(it)) }
        assertTrue(failed.joinToString("\n"), failed.isEmpty())
    }

    @Test
    fun everyResultCase() {
        val failed = failures("result_cases") { PairingResult.validate(it.get("result")) }
        assertTrue(failed.joinToString("\n"), failed.isEmpty())
    }

    @Test
    fun validCasesParseToTheirFields() {
        val request = vector.getJSONArray("request_cases").objects().first { it.getString("id") == "valid" }
        val parsed = PairingRequest.parse(compact(request)) as Parsed.Valid
        assertEquals(request.getJSONObject("body").getString("client_commit"), parsed.value.clientCommit)
        // What the phone sends is what the server accepts.
        assertNull(PairingRequest.validate(parsed.value.toJson()))
        assertEquals(parsed, PairingRequest.parse(parsed.value.toJson()))

        val reveal = PairingReveal(Pairing.newSecret())
        assertEquals(Parsed.Valid(reveal), PairingReveal.parse(reveal.toJson()))

        val result = validResult()
        val value = (PairingResult.parse(result) as Parsed.Valid).value
        assertEquals(result.getString("tls_host"), value.tlsHost)
        assertEquals(result.getString("credential_id"), value.credentialId)
        assertFalse("toString leaks the token", value.toString().contains(value.token))
    }

    @Test
    fun bytesThatAreNotOneJsonObjectAreNotAnObject() {
        for (raw in listOf("{not json".toByteArray(), byteArrayOf(0xff.toByte(), 0xfe.toByte()), "{} {}".toByteArray())) {
            assertEquals("not_object", PairingRequest.validate(raw))
            assertEquals("not_object", PairingReveal.validate(raw))
        }
    }

    @Test
    fun noncesAreRedactedWhenPrinted() {
        val nonce = Pairing.newSecret()
        assertFalse(PairingReveal(nonce).toString().contains(nonce))
        assertFalse(PairingCreated("pr-1", nonce, "2026-10-01T00:05:00Z").toString().contains(nonce))
    }

    @Test
    fun aJsonNullResultFieldIsMissing() {
        val result = validResult().put("token", JSONObject.NULL)
        assertEquals("missing_field", PairingResult.validate(result))
    }

    @Test
    fun labelLimitCountsCodePoints() {
        val request = PairingRequest("📷".repeat(64), "0.4.0", "a".repeat(64), "b".repeat(64))
        // 64 code points in 128 UTF-16 units: Python len() is 64, so it is accepted.
        assertNull(PairingRequest.validate(request.toJson()))
        assertEquals("bad_value", PairingRequest.validate(request.copy(deviceLabel = "x".repeat(65)).toJson()))
    }

    @Test
    fun pollReplies() {
        fun poll(json: JSONObject): Parsed<PollReply> = PollReply.parse(json.toString().toByteArray(UTF_8))
        assertEquals(Parsed.Valid(PollReply.Waiting("pending")), poll(JSONObject().put("state", "pending")))
        assertEquals(Parsed.Valid(PollReply.Waiting("revealed")), poll(JSONObject().put("state", "revealed")))
        assertEquals(Parsed.Valid(PollReply.Closed("rejected")), poll(JSONObject().put("state", "rejected")))
        assertEquals(Parsed.Valid(PollReply.Closed("expired")), poll(JSONObject().put("state", "expired").put("x", 1)))
        assertEquals(Parsed.Invalid("bad_value"), poll(JSONObject().put("state", "delivered")))
        assertEquals(Parsed.Invalid("bad_value"), poll(JSONObject().put("state", 3)))
        assertEquals(Parsed.Invalid("missing_field"), poll(JSONObject()))
        val approved = poll(JSONObject().put("state", "approved").put("result", validResult())) as Parsed.Valid
        assertEquals(validResult().getString("token"), (approved.value as PollReply.Approved).result.token)
        assertEquals(Parsed.Invalid("missing_field"), poll(JSONObject().put("state", "approved")))
        assertEquals(
            Parsed.Invalid("leaf_not_ca"),
            poll(JSONObject().put("state", "approved").put("result", resultCase("ca_is_leaf"))),
        )
        assertEquals(Parsed.Invalid("not_object"), PollReply.parse("[]".toByteArray()))
    }

    @Test
    fun createReplies() {
        val nonce = Pairing.newSecret()
        fun created(id: Any?, n: Any? = nonce, expires: Any? = "2026-10-01T00:05:00Z"): Parsed<PairingCreated> =
            PairingCreated.parse(
                JSONObject().put("request_id", id).put("server_nonce", n).put("expires_at", expires).put("extra", true)
                    .toString().toByteArray(UTF_8),
            )
        assertEquals(Parsed.Valid(PairingCreated("pr-abcDEF_123-xyz", nonce, "2026-10-01T00:05:00Z")), created("pr-abcDEF_123-xyz"))
        assertEquals(Parsed.Invalid("bad_value"), created("../credentials"))
        assertEquals(Parsed.Invalid("bad_value"), created("pr-1", n = "short"))
        assertEquals(Parsed.Invalid("bad_expires_at"), created("pr-1", expires = "2026-10-01T09:05:00+09:00"))
        assertEquals(Parsed.Invalid("missing_field"), created(null))
    }

    @Test
    fun confirmReplies() {
        val confirm = PairingConfirm("cred-0a1b2c3d4e5f")
        assertEquals("""{"credential_id":"cred-0a1b2c3d4e5f"}""", String(confirm.toJson(), UTF_8))
        assertNull(confirm.replyReason("""{"state":"confirmed","credential_id":"cred-0a1b2c3d4e5f"}""".toByteArray()))
        assertEquals("bad_value", confirm.replyReason("""{"state":"confirmed","credential_id":"cred-other"}""".toByteArray()))
        assertEquals("bad_value", confirm.replyReason("""{"state":"approved","credential_id":"cred-0a1b2c3d4e5f"}""".toByteArray()))
        assertEquals("not_object", confirm.replyReason("nope".toByteArray()))
    }

    private fun resultCase(id: String): JSONObject = JSONObject(
        vector.getJSONArray("result_cases").objects().first { it.getString("id") == id }.getJSONObject("result").toString(),
    )

    private fun validResult(): JSONObject = resultCase("valid")
}
