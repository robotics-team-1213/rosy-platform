package io.github.livsbittt.rosy.cam.pairing.peer

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.time.Instant
import java.util.Base64
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

internal interface CameraVaultStorage {
    fun get(id: String): String?
    fun endpointKeys(): Set<String>
    fun write(id: String, value: String, remove: Set<String>)
}

/** Approval is separate from the finite Vision credential. No bearer is stored in this record. */
data class CameraRelationship(val origin: String, val receiverId: String, val receiverPublicKey: String,
    val clientId: String, val clientKeySha256: String, val id: String, val generation: Long,
    val sourceId: String, val persistent: Boolean, val authorizationExpiresAt: Instant?, val caPem: String) {
    init {
        require(Regex("https://[a-z0-9-]+\\.local:[0-9]{1,5}").matches(origin))
        require(Regex("[a-z0-9][a-z0-9_-]{0,63}").matches(receiverId))
        CameraProof.publicKey(receiverPublicKey)
        require(Regex("[a-z0-9][a-z0-9_-]{0,63}").matches(clientId) && Regex("[0-9a-f]{64}").matches(clientKeySha256))
        require(Regex("[A-Za-z0-9_-]{32}").matches(id) && generation >= 0)
        require(Regex("[A-Za-z0-9_-]{1,32}").matches(sourceId) && persistent == (authorizationExpiresAt == null))
        require(caPem.length in 1..8192)
        val certificates = CertificateFactory.getInstance("X.509").generateCertificates(caPem.byteInputStream(Charsets.US_ASCII))
        require(certificates.size == 1 && (certificates.single() as X509Certificate).basicConstraints >= 0)
        // Expired CA/grant does not erase historical consent; operational TLS/proof checks still reject it.
    }
    fun validAt(now: Instant) = authorizationExpiresAt == null || now < authorizationExpiresAt
    override fun toString() = "CameraRelationship(receiver=$receiverId, source=$sourceId, persistent=$persistent)"
    internal fun json() = JSONObject().put("origin", origin).put("receiver_id", receiverId).put("receiver_public_key", receiverPublicKey)
        .put("client_id", clientId).put("client_key_sha256", clientKeySha256).put("id", id).put("generation", generation)
        .put("source_id", sourceId).put("persistent", persistent)
        .put("authorization_expires_at", authorizationExpiresAt?.toString() ?: JSONObject.NULL).put("ca_pem", caPem)
}

/** App-local AES-GCM approval storage. Network absence, login expiry and invalid reads never erase it. */
class CameraRelationshipVault internal constructor(private val storage: CameraVaultStorage, private val key: (Boolean) -> SecretKey) {
    constructor(context: Context) : this(preferences(context), { create -> androidKey(context, create) })
    @Synchronized fun fence(site: PairableSite) = storage.get("fence|" + slot(site)) ?: "0"
    @Synchronized fun read(site: PairableSite): CameraRelationship? {
        val value = storage.get(slot(site)) ?: return null
        return decrypt(value).also { require(it.origin == origin(site)) }
    }
    /** Historical approval remains visible even while its LAN advertisement or short credential is absent. */
    @Synchronized fun rememberedSites(): List<PairableSite> = storage.endpointKeys().take(64).mapNotNull { id ->
        storage.get(id)?.let { value -> runCatching {
            val record = decrypt(value)
            val endpoint = java.net.URI(record.origin)
            PairableSite(record.receiverId, endpoint.host, endpoint.port).also { require(origin(it) == record.origin) }
        }.getOrNull() }
    }
    private fun decrypt(value: String): CameraRelationship {
        val bytes = Base64.getDecoder().decode(value); require(bytes.size in 29..16384)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(false), GCMParameterSpec(128, bytes.copyOfRange(0, 12))) }
        val row = JSONObject(cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8))
        val result = CameraRelationship(row.getString("origin"), row.getString("receiver_id"), row.getString("receiver_public_key"),
            row.getString("client_id"), row.getString("client_key_sha256"), row.getString("id"), row.getLong("generation"),
            row.getString("source_id"), row.getBoolean("persistent"), if (row.isNull("authorization_expires_at")) null else Instant.parse(row.getString("authorization_expires_at")), row.getString("ca_pem"))
        return result
    }
    /** Authenticated camera approval and physical CA match only. This record never skips fresh session proof. */
    @Synchronized fun remember(site: PairableSite, record: CameraRelationship, expectedFence: String) {
        require(record.origin == origin(site) && fence(site) == expectedFence) { "local camera record was forgotten" }
        require(slot(site) in storage.endpointKeys() || storage.endpointKeys().size < 64) { "camera approval capacity reached" }
        val plain = record.json().toString().toByteArray(Charsets.UTF_8); require(plain.size <= 16356)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key(true)) }
        require(cipher.iv.size == 12)
        storage.write(slot(site), Base64.getEncoder().encodeToString(cipher.iv + cipher.doFinal(plain)), emptySet())
    }
    @Synchronized fun erase(site: PairableSite) {
        if (slot(site) !in storage.endpointKeys() && storage.endpointKeys().size >= 64) return
        storage.write("fence|" + slot(site), UUID.randomUUID().toString(), setOf(slot(site)))
    }
    companion object {
        fun origin(site: PairableSite): String {
            val host = SiteLink.normalizeHost(site.tlsHost)
            require(SiteLink.isTlsHost(host) && site.port in 1..65535)
            return "https://$host:${site.port}"
        }
        private fun slot(site: PairableSite) = CameraProof.hash(origin(site).toByteArray(Charsets.US_ASCII))
        private fun preferences(context: Context): CameraVaultStorage {
            val prefs = context.applicationContext.getSharedPreferences("cam-peer-relationships", Context.MODE_PRIVATE)
            return object : CameraVaultStorage {
                override fun get(id: String) = prefs.getString(id, null)
                override fun endpointKeys() = prefs.all.keys.map { it.removePrefix("fence|") }.toSet()
                override fun write(id: String, value: String, remove: Set<String>) {
                    check(prefs.edit().apply { putString(id, value); remove.forEach { remove(it) } }.commit()) { "camera approval storage unavailable" }
                }
            }
        }
        private fun androidKey(context: Context, create: Boolean): SecretKey {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (store.getKey("rosy.cam.peer.relationship.v1", null) as? SecretKey)?.let { return it }
            check(create) { "camera approval key unavailable" }
            check(context.applicationContext.getSharedPreferences("cam-peer-relationships", Context.MODE_PRIVATE).all.keys.all { it.startsWith("fence|") }) {
                "existing camera approval key unavailable"
            }
            return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder("rosy.cam.peer.relationship.v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
            }.generateKey()
        }
    }
}
