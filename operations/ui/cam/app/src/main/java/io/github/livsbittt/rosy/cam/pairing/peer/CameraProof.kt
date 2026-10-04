package io.github.livsbittt.rosy.cam.pairing.peer

import org.json.JSONObject
import java.security.KeyFactory
import java.security.PrivateKey
import java.security.PublicKey
import java.security.Signature
import java.security.MessageDigest
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.X509EncodedKeySpec
import java.security.AlgorithmParameters
import java.util.Base64

/** Python ensure_ascii compact/sorted JSON, domain separated before P256/SHA256. */
object CameraProof {
    fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    fun encodeKey(key: PublicKey): String = Base64.getEncoder().encodeToString(key.encoded)
    fun publicKey(encoded: String): ECPublicKey {
        require(encoded.length in 1..256)
        val bytes = Base64.getDecoder().decode(encoded)
        require(Base64.getEncoder().encodeToString(bytes) == encoded)
        val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(bytes)) as? ECPublicKey
            ?: throw IllegalArgumentException("P256 key required")
        val expected = AlgorithmParameters.getInstance("EC").apply { init(ECGenParameterSpec("secp256r1")) }
            .getParameterSpec(ECParameterSpec::class.java)
        require(key.params.order == expected.order && key.params.curve == expected.curve &&
            key.params.generator == expected.generator && key.params.cofactor == expected.cofactor)
        require(key.encoded.contentEquals(bytes))
        return key
    }
    fun fingerprint(encoded: String) = hash(publicKey(encoded).encoded)
    fun transcript(context: String, fields: JSONObject): ByteArray {
        require(context in setOf("request", "receiver-challenge", "session-request"))
        val bytes = canonical(JSONObject().put("version", "rosy.peer-proof/1").put("context", context).put("fields", fields))
            .toByteArray(Charsets.US_ASCII)
        require(bytes.size <= 4096)
        return bytes
    }
    fun sign(key: PrivateKey, context: String, fields: JSONObject): String = Base64.getEncoder().encodeToString(
        Signature.getInstance("SHA256withECDSA").apply { initSign(key); update(transcript(context, fields)) }.sign())
    fun verify(encoded: String, context: String, fields: JSONObject, signature: String) {
        require(signature.length in 1..128)
        val bytes = Base64.getDecoder().decode(signature)
        require(bytes.size in 8..80 && Base64.getEncoder().encodeToString(bytes) == signature)
        val valid = runCatching { Signature.getInstance("SHA256withECDSA").run {
            initVerify(publicKey(encoded)); update(transcript(context, fields)); verify(bytes)
        } }.getOrDefault(false)
        require(valid) { "peer proof rejected" }
    }
    private fun canonical(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"
        is String -> quote(value)
        is Boolean -> value.toString()
        is Int, is Long -> value.toString()
        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") { key ->
            require(key.all { it.code in 32..126 }); quote(key) + ":" + canonical(value.get(key))
        }
        else -> throw IllegalArgumentException("invalid transcript field type")
    }
    private fun quote(value: String): String = buildString {
        append('"')
        value.forEach { char -> append(when (char) {
            '"' -> "\\\""; '\\' -> "\\\\"; '\b' -> "\\b"; '\t' -> "\\t"; '\n' -> "\\n"; '\u000c' -> "\\f"; '\r' -> "\\r"
            else -> if (char.code < 32 || char.code >= 127) "\\u%04x".format(char.code) else char.toString()
        }) }
        append('"')
    }
}
