package io.github.livsbittt.rosy.cam.account

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.security.KeyStore
import java.util.Base64
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Separate from all pairing/machine vaults; Keystore ciphertext is excluded from backups. */
class AndroidAccountStore(context: Context, binding: String) : AccountStore {
    private val scope = java.security.MessageDigest.getInstance("SHA-256").digest(binding.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
    private val aad = ("rosy-account/1:" + scope).toByteArray(Charsets.US_ASCII)
    private val prefs = context.getSharedPreferences("rosy-account-$scope", Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey("rosy-account-aes", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("rosy-account-aes", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    override fun read(): String? = prefs.getString("sealed", null)?.let { text ->
        val bytes = Base64.getDecoder().decode(text); require(bytes.size in 29..262144)
        Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            updateAAD(aad); String(doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
        }
    }
    override fun write(value: String?) {
        val editor = prefs.edit()
        if (value == null) editor.remove("sealed") else {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()); updateAAD(aad) }
            editor.putString("sealed", Base64.getEncoder().encodeToString(cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))))
        }
        check(editor.commit()) { "account storage unavailable" }
    }
}

class AndroidAccount(context: Context) {
    val config = context.assets.open("account-config.json").bufferedReader().use { AccountConfig.parse(it.readText()) }
    // Public Account HTTPS trust uses the platform CA store, never pairing TOFU or site CA trust.
    private val client = accountHttpClient()
    val session = AccountSession(config, AndroidAccountStore(context, config.issuer + "\u0000" + config.clientId + "\u0000" + config.redirect), request = { endpoint, form ->
        val body = FormBody.Builder().apply { form.forEach { (k, v) -> add(k, v) } }.build()
        client.newCall(Request.Builder().url(config.issuer + "/api/fleet/auth/" + endpoint).post(body).build()).execute().use { response ->
            check(response.isSuccessful) { "account request rejected" }
            val stream = response.body?.byteStream() ?: error("account response missing")
            val bytes = stream.readBytesLimited(65536)
            if (bytes.isEmpty() && endpoint == "revoke") JSONObject() else JSONObject(String(bytes, Charsets.UTF_8))
        }
    })
    fun launch(activity: Activity, resource: String) {
        activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(session.begin(resource))).addCategory(Intent.CATEGORY_BROWSABLE))
    }
    fun manageProfile(activity: Activity) {
        activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(session.profileUrl)).addCategory(Intent.CATEGORY_BROWSABLE))
    }
    fun isCallback(intent: Intent?): Boolean = intent?.action == Intent.ACTION_VIEW && intent.data?.let {
        it.scheme == "https" && it.host == Uri.parse(config.redirect).host && it.path == Uri.parse(config.redirect).path
    } == true
    companion object {
        fun configured(context: Context): Boolean = context.assets.list("")?.contains("account-config.json") == true
    }
}
private fun java.io.InputStream.readBytesLimited(limit: Int): ByteArray {
    val out = java.io.ByteArrayOutputStream(); val buffer = ByteArray(4096)
    while (true) { val n = read(buffer); if (n < 0) break; require(out.size() + n <= limit); out.write(buffer, 0, n) }
    return out.toByteArray()
}

internal fun accountHttpClient(): OkHttpClient = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
    .connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).callTimeout(3, TimeUnit.SECONDS).build()
