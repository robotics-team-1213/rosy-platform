package io.github.livsbittt.rosy.pilot

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.security.KeyStore
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

internal interface VaultStorage {
    fun get(id: String): String?
    fun write(id: String, value: String, remove: Set<String>)
}
enum class SavedLoginStatus { NONE, READY, EXPIRED, UNAVAILABLE }
data class SavedLogin(val status: SavedLoginStatus, val session: LobbySession? = null)

/** Stored login records survive transient failures; each session still requires current validation. */
class PairingVault internal constructor(private val storage: VaultStorage, private val key: () -> SecretKey,
    private val now: () -> Instant = { Instant.now() }) {
    constructor(context: Context) : this(preferences(context), { androidKey() })
    fun inspect(candidate: Candidate, offer: LobbyOffer, store: CandidateStore): SavedLogin {
        if (storage.get(forgetSlot(candidate)) != null) return SavedLogin(SavedLoginStatus.NONE)
        val stable = stableSlot(candidate)
        val stableRecord = stable?.let { storage.get(it) }
        val encoded = stableRecord ?: storage.get(legacySlot(candidate)) ?: return SavedLogin(SavedLoginStatus.NONE)
        return try {
            val bytes = Base64.getDecoder().decode(encoded); require(bytes.size in 29..8192)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            }
            val row = JSONObject(cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8))
            if (stableRecord != null) require(row.getString("origin") == origin(candidate))
            val robotId = row.getString("robot_id")
            require(Regex("rosy_(?:0[1-9]|[1-9][0-9]*)").matches(robotId))
            require(offer.mode == "paired" && (offer.robotId.isEmpty() || robotId == offer.robotId))
            val expiry = Instant.parse(row.getString("expires_at"))
            if (expiry <= now()) return SavedLogin(SavedLoginStatus.EXPIRED)
            require(store.matches(candidate, robotId))
            val target = RobotTarget(robotId, candidate.host, candidate.port, row.getString("credential"))
            SavedLogin(SavedLoginStatus.READY, LobbySession(target, candidate.secure, expiry, candidate, store))
        } catch (_: Exception) { SavedLogin(SavedLoginStatus.UNAVAILABLE) }
    }
    fun load(candidate: Candidate, offer: LobbyOffer, store: CandidateStore) = inspect(candidate, offer, store).session
    /** Call only after authenticated whoami/pairing and system/info identity verification. */
    fun saveVerified(candidate: Candidate, session: LobbySession) {
        require(session.authorized() && session.target.host == candidate.host && session.target.port == candidate.port && session.secure == candidate.secure)
        val stable = stableSlot(candidate)
        val row = JSONObject().put("robot_id", session.target.id).put("credential", session.target.credential)
            .put("expires_at", session.expiresAt.toString())
        if (stable != null) row.put("origin", origin(candidate))
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.iv + cipher.doFinal(row.toString().toByteArray(Charsets.UTF_8))
        storage.write(stable ?: legacySlot(candidate), Base64.getEncoder().encodeToString(encrypted),
            setOfNotNull(forgetSlot(candidate), if (stable != null) legacySlot(candidate) else null))
    }
    /** Local forgetting does not revoke the receiver's credential or approval. */
    fun erase(candidate: Candidate) {
        storage.write(forgetSlot(candidate), "forgotten", setOfNotNull(stableSlot(candidate), legacySlot(candidate)))
    }
    private fun forgetSlot(candidate: Candidate) = hash("forgotten|${candidate.host.lowercase(java.util.Locale.ROOT).trimEnd('.')}|${candidate.port}|${candidate.secure}")
    private fun origin(candidate: Candidate) = "https://${candidate.host.lowercase(java.util.Locale.ROOT).trimEnd('.')}:${candidate.port}"
    private fun stableSlot(candidate: Candidate): String? = if (candidate.secure && SiteLink.isTlsHost(candidate.host)) hash("v2|${origin(candidate)}") else null
    internal fun legacySlot(candidate: Candidate) = hash("${candidate.host}|${candidate.port}|${candidate.secure}|${candidate.addresses.sorted().joinToString(",")}")
    private fun hash(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    companion object {
        private const val ALIAS = "rosy.pilot.pair.v1"
        private fun preferences(context: Context): VaultStorage {
            val prefs = context.applicationContext.getSharedPreferences("pilot-pairings", Context.MODE_PRIVATE)
            return object : VaultStorage {
                override fun get(id: String) = prefs.getString(id, null)
                override fun write(id: String, value: String, remove: Set<String>) {
                    prefs.edit().apply { putString(id, value); remove.forEach { remove(it) } }.apply()
                }
            }
        }
        private fun androidKey(): SecretKey {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            return (store.getKey(ALIAS, null) as? SecretKey) ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
            }.generateKey()
        }
    }
}
