package io.github.livsbittt.rosy.cam.pairing.peer

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec

class CameraProofTest {
    @Test fun pythonGoldenTranscriptsMatchIncludingKoreanAndSurrogatePairs() {
        val fixture = JSONObject(javaClass.getResourceAsStream("/camera-peer-transcripts.json")!!.bufferedReader().readText())
        val vectors = fixture.getJSONArray("vectors")
        for (index in 0 until vectors.length()) {
            val row = vectors.getJSONObject(index)
            val bytes = CameraProof.transcript(row.getString("context"), row.getJSONObject("fields"))
            assertEquals(row.getString("ascii"), bytes.toString(Charsets.US_ASCII))
            assertEquals(row.getString("sha256"), CameraProof.hash(bytes))
        }
    }
    @Test fun p256ProofBindsCameraProfileAndFields() {
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val fields = JSONObject().put("nonce", "a".repeat(64)).put("generation", 0).put("label", "현장 😀")
            .put("profile", "rosy.camera-peer/1").put("audience", "fleet-camera-ingest")
            .put("device_kind", "overhead-camera").put("source_role", "camera")
        val publicKey = CameraProof.encodeKey(key.public)
        val signature = CameraProof.sign(key.private, "request", fields)
        CameraProof.verify(publicKey, "request", fields, signature)
        fields.put("audience", "core-operator")
        assertThrows(IllegalArgumentException::class.java) { CameraProof.verify(publicKey, "request", fields, signature) }
        fields.put("audience", "fleet-camera-ingest")
        assertThrows(IllegalArgumentException::class.java) { CameraProof.verify(publicKey, "receiver-challenge", fields, signature) }
        fields.put("generation", 1)
        assertThrows(IllegalArgumentException::class.java) { CameraProof.verify(publicKey, "request", fields, signature) }
        assertThrows(IllegalArgumentException::class.java) { CameraProof.publicKey(publicKey.trimEnd('=')) }
    }
    @Test fun otherCurveAndAmbiguousJsonNumbersFailClosed() {
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp384r1")) }.generateKeyPair()
        assertThrows(IllegalArgumentException::class.java) { CameraProof.publicKey(CameraProof.encodeKey(key.public)) }
        assertThrows(IllegalArgumentException::class.java) { CameraProof.transcript("request", JSONObject().put("generation", 0.5)) }
    }
    @Test fun realPythonSignatureAndJavaSignatureShareTheCanonicalWire() {
        val fixture = JSONObject(javaClass.getResourceAsStream("/camera-peer-transcripts.json")!!.bufferedReader().readText()).getJSONObject("python_signature")
        CameraProof.verify(fixture.getString("public_key"), fixture.getString("context"), fixture.getJSONObject("fields"), fixture.getString("signature"))
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val fields = JSONObject().put("label", "현장 😀 / \u007f").put("generation", 0).put("nonce", "a".repeat(64))
        val signature = CameraProof.sign(key.private, "session-request", fields)
        CameraProof.verify(CameraProof.encodeKey(key.public), "session-request", fields, signature)
        System.getenv("ROSY_PEER_TEST_OUTPUT")?.let { path -> java.io.File(path).writeText(JSONObject()
            .put("context", "session-request").put("fields", fields).put("public_key", CameraProof.encodeKey(key.public)).put("signature", signature).toString()) }
    }
}
