package io.github.livsbittt.rosy.pilot

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec

class PeerCryptoTest {
    @Test fun pythonGoldenTranscriptsMatchIncludingKoreanAndSurrogatePairs() {
        val fixture = JSONObject(javaClass.getResourceAsStream("/peer-transcripts.json")!!.bufferedReader().readText())
        val vectors = fixture.getJSONArray("vectors")
        for (index in 0 until vectors.length()) {
            val row = vectors.getJSONObject(index)
            val bytes = PeerProof.transcript(row.getString("context"), row.getJSONObject("fields"))
            assertEquals(row.getString("ascii"), bytes.toString(Charsets.US_ASCII))
            assertEquals(row.getString("sha256"), PeerProof.hash(bytes))
        }
    }
    @Test fun realP256SignaturesCannotMoveBetweenContextOrFields() {
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val fields = JSONObject().put("nonce", "a".repeat(64)).put("generation", 0).put("label", "현장 😀")
        val publicKey = PeerProof.encodeKey(key.public)
        val signature = PeerProof.sign(key.private, "request", fields)
        PeerProof.verify(publicKey, "request", fields, signature)
        assertThrows(IllegalArgumentException::class.java) { PeerProof.verify(publicKey, "receiver-challenge", fields, signature) }
        fields.put("generation", 1)
        assertThrows(IllegalArgumentException::class.java) { PeerProof.verify(publicKey, "request", fields, signature) }
        assertThrows(IllegalArgumentException::class.java) { PeerProof.publicKey(publicKey.trimEnd('=')) }
    }
    @Test fun otherCurveAndAmbiguousJsonNumbersFailClosed() {
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp384r1")) }.generateKeyPair()
        assertThrows(IllegalArgumentException::class.java) { PeerProof.publicKey(PeerProof.encodeKey(key.public)) }
        assertThrows(IllegalArgumentException::class.java) { PeerProof.transcript("request", JSONObject().put("generation", 0.5)) }
    }
    @Test fun realPythonSignatureAndJavaSignatureShareTheCanonicalWire() {
        val fixture = JSONObject(javaClass.getResourceAsStream("/peer-transcripts.json")!!.bufferedReader().readText()).getJSONObject("python_signature")
        PeerProof.verify(fixture.getString("public_key"), fixture.getString("context"), fixture.getJSONObject("fields"), fixture.getString("signature"))
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val fields = JSONObject().put("label", "현장 😀 / \u007f").put("generation", 0).put("nonce", "a".repeat(64))
        val signature = PeerProof.sign(key.private, "session-request", fields)
        PeerProof.verify(PeerProof.encodeKey(key.public), "session-request", fields, signature)
        System.getenv("ROSY_PEER_TEST_OUTPUT")?.let { path -> java.io.File(path).writeText(JSONObject()
            .put("context", "session-request").put("fields", fields).put("public_key", PeerProof.encodeKey(key.public)).put("signature", signature).toString()) }
    }
}
