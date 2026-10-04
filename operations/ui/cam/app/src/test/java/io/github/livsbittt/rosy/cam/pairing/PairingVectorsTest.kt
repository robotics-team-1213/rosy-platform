package io.github.livsbittt.rosy.cam.pairing

import java.io.File
import java.nio.charset.StandardCharsets.UTF_8
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * D-341 19: the Kotlin port follows test/fixtures/protocol/pairing.v1.json, the vector core_common
 * `pairing.py` (Fleet, Vision) reads. Every case of every list runs; counts are only required to be non-zero.
 */
class PairingVectorsTest {
    companion object {
        val vector: JSONObject by lazy {
            val path = System.getProperty("rosy.pairing.vectors")
                ?: error("system property rosy.pairing.vectors is not set (see app/build.gradle.kts)")
            JSONObject(File(path).readText(UTF_8))
        }

        fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }

        fun JSONArray.strings(): List<String> = (0 until length()).map { getString(it) }

        /** Null for a valid case, else its reason. */
        fun JSONObject.expectedReason(validKey: String = "valid"): String? =
            getJSONObject("expect").let { if (it.getBoolean(validKey)) null else it.getString("reason") }
    }

    private fun code(case: JSONObject): String = Pairing.confirmationCode(
        role = case.getString("role"),
        requestId = case.getString("request_id"),
        leafCertSha256 = case.getString("leaf_cert_sha256"),
        clientNonce = case.getString("client_nonce"),
        serverNonce = case.getString("server_nonce"),
    )

    @Test
    fun constantsAreTheVectorConstants() {
        assertEquals(vector.getString("proto"), Pairing.PROTO)
        assertEquals(vector.getString("role"), Pairing.ROLE)
        assertEquals(vector.getInt("max_request_bytes"), Pairing.MAX_REQUEST_BYTES)
        assertEquals(vector.getJSONArray("request_reasons").strings(), Pairing.REQUEST_REASONS)
        assertEquals(vector.getJSONArray("result_reasons").strings(), Pairing.RESULT_REASONS)
        assertEquals(vector.getJSONArray("pairable_reasons_added").strings(), Pairing.PAIRABLE_REASONS_ADDED)
    }

    @Test
    fun everyCodeCase() {
        val cases = vector.getJSONArray("code_cases").objects()
        assertTrue("no code cases", cases.isNotEmpty())
        for (case in cases) {
            val id = case.getString("id")
            assertEquals(id, case.getString("code"), code(case))
            assertEquals(id, case.getString("client_commit"), Pairing.commit(case.getString("client_nonce")))
        }
    }

    @Test
    fun aRelayedLeafChangesTheCode() {
        val byId = vector.getJSONArray("code_cases").objects().associateBy { it.getString("id") }
        val pairs = vector.getJSONArray("code_pairs_differing_only_in_leaf")
        assertTrue("no leaf pairs", pairs.length() >= 1)
        for (i in 0 until pairs.length()) {
            val (first, second) = pairs.getJSONArray(i).strings().map { byId.getValue(it) }
            val differing = first.keySet().filter { first.get(it) != second.opt(it) }.toSet() - setOf("id", "code")
            assertEquals(setOf("leaf_cert_sha256"), differing)
            assertNotEquals(first.getString("code"), second.getString("code"))
            assertNotEquals(code(first), code(second))
        }
    }

    @Test
    fun aTamperedVectorFails() {
        val case = JSONObject(vector.getJSONArray("code_cases").getJSONObject(0).toString())
        case.put("server_nonce", case.getString("server_nonce").dropLast(1) + "y")
        assertNotEquals(case.getString("code"), code(case))
    }

    @Test
    fun everyFingerprintCase() {
        val cases = vector.getJSONArray("fingerprint_cases").objects()
        assertTrue("no fingerprint cases", cases.isNotEmpty())
        var withPem = 0
        for (case in cases) {
            val id = case.getString("id")
            val want = case.getString("fingerprint")
            assertEquals(id, want, Pairing.fingerprintFromSha256(case.getString("der_sha256")))
            if (case.has("ca_pem")) {
                val pem = case.getString("ca_pem")
                assertEquals(id, case.getString("der_sha256"), Pairing.derSha256(pem))
                assertEquals(id, want, Pairing.siteFingerprint(pem))
                // Only the first block counts (pairing.py der_sha256).
                assertEquals(id, case.getString("der_sha256"), Pairing.derSha256(pem + pem))
                withPem++
            }
            assertTrue(id, Pairing.sameFingerprint(want, want.lowercase().replace("-", " ")))
        }
        assertTrue("no fingerprint case carries a PEM", withPem >= 1)
    }

    @Test
    fun fingerprintComparisonNeedsSixteenHexDigits() {
        assertFalse(Pairing.sameFingerprint("0998-86F9-E7D2-2563", "0998-86F9-E7D2-2564"))
        assertFalse(Pairing.sameFingerprint("0998-86F9-E7D2", "0998-86F9-E7D2"))
        assertFalse(Pairing.sameFingerprint("", ""))
        assertTrue(runCatching { Pairing.fingerprintFromSha256("0998") }.isFailure)
        assertTrue(runCatching { Pairing.derSha256("no certificate here") }.isFailure)
    }

    @Test
    fun everyPairableCase() {
        val cases = vector.getJSONArray("pairable_cases").objects()
        assertTrue("no pairable cases", cases.isNotEmpty())
        for (case in cases) {
            val txt = case.getJSONArray("txt").strings()
                .associate { it.substringBefore('=') to it.substringAfter('=').toByteArray(UTF_8) }
            val got = Pairing.pairable(
                case.getString("service_type"),
                case.optString("host").takeIf { case.has("host") && !case.isNull("host") },
                case.optString("address").takeIf { case.has("address") && !case.isNull("address") },
                case.getInt("port"),
                txt,
            )
            assertEquals(case.getString("id"), case.expectedReason("pairable"), got)
        }
    }

    @Test
    fun newSecretIs43CharBase64urlAndCommitIsItsDigest() {
        val nonce = Pairing.newSecret()
        assertTrue(nonce, Pairing.SECRET_PATTERN.matches(nonce))
        assertTrue(Pairing.SHA256_HEX.matches(Pairing.commit(nonce)))
        assertNotEquals(nonce, Pairing.newSecret())
    }
}
