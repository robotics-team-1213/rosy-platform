package io.github.livsbittt.rosy.pilot

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import org.json.JSONObject
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.spec.ECGenParameterSpec

interface PeerSigner {
    val publicKey: String
    val clientId: String get() = "pilot_" + PeerProof.fingerprint(publicKey).take(32)
    fun sign(context: String, fields: JSONObject): String
}

/** The private key is generated in AndroidKeystore and is never exported or removed by local forgetting. */
class AndroidPeerIdentity(context: Context) : PeerSigner {
    private val preferences = context.applicationContext.getSharedPreferences("pilot-peer-identity", Context.MODE_PRIVATE)
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    @Synchronized private fun existingOrCreate() {
        if (keyStore.containsAlias(ALIAS)) return
        check(!preferences.getBoolean("issued", false)) { "remembered peer identity unavailable" }
        KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
            initialize(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1")).setDigests(KeyProperties.DIGEST_SHA256).build())
        }.generateKeyPair()
        check(preferences.edit().putBoolean("issued", true).commit()) { "identity marker unavailable" }
    }
    override val publicKey: String get() { existingOrCreate(); return PeerProof.encodeKey(keyStore.getCertificate(ALIAS).publicKey) }
    override fun sign(context: String, fields: JSONObject): String {
        existingOrCreate()
        return PeerProof.sign(keyStore.getKey(ALIAS, null) as PrivateKey, context, fields)
    }
    private companion object { const val ALIAS = "rosy.pilot.peer.identity.v1" }
}
