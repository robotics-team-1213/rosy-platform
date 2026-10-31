package io.github.livsbittt.rosy.peer

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
    val clientId: String
    fun sign(context: String, fields: JSONObject): String
}

/**
 * The private key is generated in AndroidKeystore and is never exported or removed by local forgetting.
 * [app] ("pilot", "cam") keeps each app's existing key alias, marker and client id prefix, so pairings survive.
 */
class AndroidPeerIdentity(context: Context, private val app: String) : PeerSigner {
    init { require(app in setOf("pilot", "cam")) }
    private val alias = "rosy.$app.peer.identity.v1"
    private val preferences = context.applicationContext.getSharedPreferences("$app-peer-identity", Context.MODE_PRIVATE)
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    @Synchronized private fun existingOrCreate() {
        if (keyStore.containsAlias(alias)) return
        check(!preferences.getBoolean("issued", false)) { "remembered peer identity unavailable" }
        KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
            initialize(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1")).setDigests(KeyProperties.DIGEST_SHA256).build())
        }.generateKeyPair()
        check(preferences.edit().putBoolean("issued", true).commit()) { "identity marker unavailable" }
    }
    override val publicKey: String get() { existingOrCreate(); return PeerProof.encodeKey(keyStore.getCertificate(alias).publicKey) }
    override fun sign(context: String, fields: JSONObject): String {
        existingOrCreate()
        return PeerProof.sign(keyStore.getKey(alias, null) as PrivateKey, context, fields)
    }
    override val clientId: String get() = app + "_" + PeerProof.fingerprint(publicKey).take(32)
}
