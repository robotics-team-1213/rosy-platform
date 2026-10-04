package io.github.livsbittt.rosy.pilot

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

/** Paired credentials stay encrypted and endpoint-bound. Development credentials are never persisted. */
class PairingVault(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences("pilot-pairings", Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return (store.getKey(ALIAS, null) as? SecretKey) ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun load(candidate: Candidate, offer: LobbyOffer, store: CandidateStore): LobbySession? {
        val id = slot(candidate)
        val encoded = preferences.getString(id, null) ?: return null
        return try {
            val bytes = Base64.getDecoder().decode(encoded)
            require(bytes.size in 29..8192)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12))) }
            val row = JSONObject(cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8))
            val robotId = row.getString("robot_id")
            require(Regex("rosy_(?:0[1-9]|[1-9][0-9]*)").matches(robotId))
            require(offer.robotId.isEmpty() || robotId == offer.robotId)
            require(store.matches(candidate, robotId))
            val expiry = Instant.parse(row.getString("expires_at")); require(expiry > Instant.now())
            val target = RobotTarget(robotId, candidate.host, candidate.port, row.getString("credential"))
            LobbySession(target, candidate.secure, expiry, candidate, store)
        } catch (_: Exception) { preferences.edit().remove(id).apply(); null }
    }
    fun save(candidate: Candidate, session: LobbySession) {
        val row = JSONObject().put("robot_id", session.target.id).put("credential", session.target.credential).put("expires_at", session.expiresAt.toString())
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted = cipher.iv + cipher.doFinal(row.toString().toByteArray())
        preferences.edit().putString(slot(candidate), Base64.getEncoder().encodeToString(encrypted)).apply()
    }
    fun erase(candidate: Candidate) { preferences.edit().remove(slot(candidate)).apply() }
    private fun slot(candidate: Candidate) = MessageDigest.getInstance("SHA-256").digest(
        "${candidate.host}|${candidate.port}|${candidate.secure}|${candidate.addresses.sorted().joinToString(",")}".toByteArray())
        .joinToString("") { "%02x".format(it) }
    companion object { private const val ALIAS = "rosy.pilot.pair.v1" }
}
