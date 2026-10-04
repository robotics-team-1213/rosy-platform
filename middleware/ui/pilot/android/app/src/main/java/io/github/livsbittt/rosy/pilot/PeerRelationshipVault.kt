package io.github.livsbittt.rosy.pilot

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.security.KeyStore
import java.time.Instant
import java.util.Base64
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

internal interface PeerVaultStorage : VaultStorage { fun endpointKeys(): Set<String> }

data class PeerRelationship(val origin: String, val receiverId: String, val receiverPublicKey: String,
    val clientId: String, val clientKeySha256: String, val id: String, val role: String, val generation: Long,
    val persistent: Boolean, val authorizationExpiresAt: Instant?, val caPem: String? = null) {
    init {
        require(Regex("https://[a-z0-9-]+\\.local:[0-9]{1,5}").matches(origin))
        require(Regex("rosy_(?:0[1-9]|[1-9][0-9]*)").matches(receiverId))
        PeerProof.publicKey(receiverPublicKey)
        require(Regex("[a-z0-9][a-z0-9_-]{0,63}").matches(clientId) && Regex("[0-9a-f]{64}").matches(clientKeySha256))
        require(Regex("[A-Za-z0-9_-]{32}").matches(id) && role in setOf("viewer", "operator") && generation >= 0)
        require(persistent == (authorizationExpiresAt == null))
    }
    override fun toString() = "PeerRelationship(receiver=$receiverId, role=$role, persistent=$persistent)"
    fun validAt(now: Instant) = authorizationExpiresAt == null || now < authorizationExpiresAt
    internal fun json() = JSONObject().put("origin", origin).put("receiver_id", receiverId).put("receiver_public_key", receiverPublicKey)
        .put("client_id", clientId).put("client_key_sha256", clientKeySha256).put("id", id).put("role", role)
        .put("generation", generation).put("persistent", persistent).put("authorization_expires_at", authorizationExpiresAt?.toString() ?: JSONObject.NULL)
        .put("ca_pem", caPem ?: JSONObject.NULL)
}

/** Durable approval has its own encrypted store; neither login expiry nor discovery failure erases it. */
class PeerRelationshipVault internal constructor(private val storage: PeerVaultStorage, private val key: (Boolean) -> SecretKey) {
    constructor(context: Context) : this(preferences(context), { create -> androidKey(context, create) })
    @Synchronized fun fence(candidate: Candidate) = storage.get("fence|" + slot(candidate)) ?: "0"
    @Synchronized fun read(candidate: Candidate): PeerRelationship? {
        val encoded = storage.get(slot(candidate)) ?: return null
        val bytes = Base64.getDecoder().decode(encoded); require(bytes.size in 29..8192)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(false), GCMParameterSpec(128, bytes.copyOfRange(0, 12))) }
        val row = JSONObject(cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8))
        val result = PeerRelationship(row.getString("origin"), row.getString("receiver_id"), row.getString("receiver_public_key"),
            row.getString("client_id"), row.getString("client_key_sha256"), row.getString("id"), row.getString("role"),
            row.getLong("generation"), row.getBoolean("persistent"), if (row.isNull("authorization_expires_at")) null else Instant.parse(row.getString("authorization_expires_at")),
            if (row.isNull("ca_pem")) null else row.getString("ca_pem"))
        require(result.origin == origin(candidate) && (candidate.robotId.isEmpty() || result.receiverId == candidate.robotId))
        return result
    }
    /** Authenticated approval and any required physical CA match reach this call.
     * The saved decision is not a session: fresh receiver key proof is always required. */
    @Synchronized fun remember(candidate: Candidate, record: PeerRelationship, expectedFence: String) {
        require(record.origin == origin(candidate) && fence(candidate) == expectedFence) { "local record was forgotten" }
        require(slot(candidate) in storage.endpointKeys() || storage.endpointKeys().size < 64) { "local approval capacity reached" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key(true)) }
        storage.write(slot(candidate), Base64.getEncoder().encodeToString(cipher.iv + cipher.doFinal(record.json().toString().toByteArray(Charsets.UTF_8))), emptySet())
    }
    @Synchronized fun erase(candidate: Candidate) {
        if (slot(candidate) !in storage.endpointKeys() && storage.endpointKeys().size >= 64) return
        storage.write("fence|" + slot(candidate), UUID.randomUUID().toString(), setOf(slot(candidate)))
    }
    companion object {
        fun origin(candidate: Candidate): String {
            require(candidate.secure && SiteLink.isTlsHost(candidate.host) && candidate.port in 1..65535)
            return "https://${candidate.host}:${candidate.port}"
        }
        private fun slot(candidate: Candidate) = PeerProof.hash(origin(candidate).toByteArray(Charsets.US_ASCII))
        private fun preferences(context: Context): PeerVaultStorage {
            val prefs = context.applicationContext.getSharedPreferences("pilot-peer-relationships", Context.MODE_PRIVATE)
            return object : PeerVaultStorage {
                override fun get(id: String) = prefs.getString(id, null)
                override fun endpointKeys() = prefs.all.keys.map { it.removePrefix("fence|") }.toSet()
                override fun write(id: String, value: String, remove: Set<String>) {
                    check(prefs.edit().apply { putString(id, value); remove.forEach { remove(it) } }.commit()) { "approval storage unavailable" }
                }
            }
        }
        private fun androidKey(context: Context, create: Boolean): SecretKey {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (store.getKey("rosy.pilot.relationship.v1", null) as? SecretKey)?.let { return it }
            check(create) { "approval encryption key unavailable" }
            check(context.applicationContext.getSharedPreferences("pilot-peer-relationships", Context.MODE_PRIVATE).all.keys.all { it.startsWith("fence|") }) {
                "existing approval encryption key unavailable"
            }
            return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder("rosy.pilot.relationship.v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
            }.generateKey()
        }
    }
}
