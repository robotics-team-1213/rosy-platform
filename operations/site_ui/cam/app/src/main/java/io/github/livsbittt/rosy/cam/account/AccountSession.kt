package io.github.livsbittt.rosy.cam.account

import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer

/** Public deployment trust only. Never learned from discovery or an incoming intent. */
class AccountConfig(val issuer: String, val clientId: String, val redirect: String,
    val resources: Set<String>, val keys: Map<String, ByteArray>, val robots: List<JSONObject>) {
    companion object {
        fun parse(text: String): AccountConfig {
            require(text.length <= 65536)
            val o = JSONObject(text)
            fun https(value: String): String {
                val url = value.toHttpUrl()
                require(url.isHttps && url.username.isEmpty() && url.password.isEmpty() && url.fragment == null && url.query == null)
                return value
            }
            val issuer = https(o.getString("issuer")); require(issuer.toHttpUrl().encodedPath == "/" && !issuer.endsWith('/'))
            val redirect = https(o.getString("redirect_uri"))
            val client = o.getString("client_id"); require(client.matches(Regex("[A-Za-z0-9._-]{1,96}")))
            val resources = o.getJSONArray("resources").let { a -> (0 until a.length()).map { a.getString(it) }.toSet() }
            require(resources.isNotEmpty() && resources.size <= 64 && resources.all { it.matches(Regex("(site|robot):[A-Za-z0-9._-]{1,96}")) })
            val k = o.getJSONObject("trusted_keys")
            val keys = k.keys().asSequence().associateWith { Base64.getUrlDecoder().decode(k.getString(it)).also { b -> require(b.size == 32) } }
            require(keys.isNotEmpty() && keys.size <= 8)
            val robots = o.optJSONArray("robots")?.let { a -> (0 until a.length()).map { a.getJSONObject(it) } }.orEmpty()
            return AccountConfig(issuer, client, redirect, resources, keys, robots)
        }
    }
}

interface AccountStore { fun read(): String?; fun write(value: String?) }

/** All callers run off the UI thread. One lock prevents refresh rotation racing itself or logout. */
class AccountSession(private val config: AccountConfig, private val store: AccountStore,
    private val request: (String, Map<String, String>) -> JSONObject,
    private val clock: () -> Long = { System.currentTimeMillis() / 1000 }) {
    private var data = store.read()?.let { JSONObject(it) } ?: JSONObject()
    @Volatile private var stopSnapshot: Map<String, String> = emptyMap()
    private val checked = mutableMapOf<String, Long>()
    private fun save() { store.write(data.toString()) }
    private fun random() = Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32).also { SecureRandom().nextBytes(it) })
    @Synchronized fun begin(resource: String): String {
        require(resource in config.resources)
        val state = random(); val verifier = random()
        data.put("pending", JSONObject().put("state", state).put("verifier", verifier).put("resource", resource).put("expires", clock() + 300))
        save()
        val challenge = Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(Charsets.US_ASCII)))
        return (config.issuer + "/api/fleet/auth/authorize").toHttpUrl().newBuilder()
            .addQueryParameter("response_type", "code").addQueryParameter("client_id", config.clientId)
            .addQueryParameter("redirect_uri", config.redirect).addQueryParameter("scope", resource)
            .addQueryParameter("state", state).addQueryParameter("code_challenge", challenge)
            .addQueryParameter("code_challenge_method", "S256").build().toString()
    }
    @Synchronized fun complete(callback: String): String {
        require(callback.length <= 8192)
        val url = callback.toHttpUrl(); val expected = config.redirect.toHttpUrl()
        require(url.newBuilder().query(null).fragment(null).build() == expected && url.fragment == null)
        require(url.queryParameterNames == setOf("code", "state") && url.queryParameterValues("code").size == 1 && url.queryParameterValues("state").size == 1)
        val pending = data.optJSONObject("pending") ?: throw IllegalArgumentException("login expired")
        require(pending.getLong("expires") > clock() && MessageDigest.isEqual(pending.getString("state").toByteArray(), url.queryParameter("state")!!.toByteArray()))
        data.remove("pending"); save() // a code is never retried after a possibly successful exchange
        val resource = pending.getString("resource")
        val result = request("token", mapOf("grant_type" to "authorization_code", "client_id" to config.clientId,
            "redirect_uri" to config.redirect, "code" to url.queryParameter("code")!!, "code_verifier" to pending.getString("verifier")))
        accept(resource, result, switching = true)
        return resource
    }
    private fun claims(token: String, resource: String): JSONObject {
        require(token.length <= 16384)
        val parts = token.split('.'); require(parts.size == 3)
        val header = JSONObject(String(Base64.getUrlDecoder().decode(parts[0]), Charsets.UTF_8))
        require(header.getString("alg") == "EdDSA" && !header.has("crit"))
        val key = config.keys[header.getString("kid")] ?: throw IllegalArgumentException("untrusted account key")
        val signer = Ed25519Signer(); signer.init(false, Ed25519PublicKeyParameters(key, 0))
        val signed = "${parts[0]}.${parts[1]}".toByteArray(Charsets.US_ASCII); signer.update(signed, 0, signed.size)
        require(signer.verifySignature(Base64.getUrlDecoder().decode(parts[2])))
        val c = JSONObject(String(Base64.getUrlDecoder().decode(parts[1]), Charsets.UTF_8)); val now = clock()
        require(c.getString("iss") == config.issuer && c.getString("aud") == resource)
        require(c.getLong("exp") > now && c.getLong("iat") <= now + 10 && c.getLong("exp") - c.getLong("iat") <= 300)
        require(c.getString("sub").isNotBlank() && c.getString("sid").isNotBlank() && c.getLong("rev") >= 1)
        return c
    }
    private fun accept(resource: String, result: JSONObject, switching: Boolean = false) {
        require(result.getString("token_type").equals("Bearer", true))
        val c = claims(result.getString("access_token"), resource)
        require(result.getString("refresh_token").length in 20..2048)
        val previous = data.optString("subject")
        if (previous.isNotEmpty() && previous != c.getString("sub")) {
            require(switching) { "refresh changed identity" }
            val old = data.optJSONObject("tokens")
            data.remove("tokens"); stopSnapshot = emptyMap(); checked.clear(); save()
            old?.keys()?.forEach { r -> runCatching { request("revoke", mapOf("token" to old.getJSONObject(r).getString("refresh_token"))) } }
        }
        data.put("subject", c.getString("sub"))
        val tokens = data.optJSONObject("tokens") ?: JSONObject().also { data.put("tokens", it) }
        tokens.put(resource, result); stopSnapshot = stopSnapshot + (resource to result.getString("access_token")); checked.remove(resource); save()
    }
    @Synchronized fun access(resource: String): String? {
        require(resource in config.resources)
        val tokens = data.optJSONObject("tokens") ?: return null
        var result = tokens.optJSONObject(resource) ?: return null
        try {
            val current = runCatching { claims(result.getString("access_token"), resource) }.getOrNull()
            if (current == null || current.getLong("exp") <= clock() + 30) {
                result = request("token", mapOf("grant_type" to "refresh_token", "client_id" to config.clientId,
                    "refresh_token" to result.getString("refresh_token")))
                accept(resource, result)
            }
            val token = result.getString("access_token"); val c = claims(token, resource)
            if (clock() - (checked[resource] ?: 0) >= 15) {
                val state = request("introspect", mapOf("token" to token))
                require(state.optBoolean("active") && state.getString("sub") == c.getString("sub") && state.getString("aud") == resource)
                checked[resource] = clock()
            }
            stopSnapshot = stopSnapshot + (resource to token)
            return token
        } catch (e: Exception) {
            // Fail closed and never replay a possibly consumed rotating refresh credential.
            tokens.remove(resource); stopSnapshot = stopSnapshot - resource; checked.remove(resource); save(); return null
        }
    }
    fun cachedAccess(resource: String): String? = runCatching {
        stopSnapshot[resource]?.also { claims(it, resource) }
    }.getOrNull()
    @Synchronized fun identity(resource: String): String? = runCatching {
        val token = data.getJSONObject("tokens").getJSONObject(resource).getString("access_token")
        val c = claims(token, resource); "${c.getString("sub")}:${c.getString("sid")}:${c.getLong("rev")}"
    }.getOrNull()
    @Synchronized fun context(resource: String): JSONObject? = access(resource)?.let {
        val c = claims(it, resource)
        JSONObject().put("enabled", true).put("authenticated", true).put("account_id", c.getString("sub"))
            .put("session_family", c.getString("sid")).put("revision", c.getLong("rev")).put("resource", resource)
            .put("capabilities", c.getJSONArray("grants").let { grants ->
                val caps = org.json.JSONArray()
                for (i in 0 until grants.length()) { val g = grants.getJSONObject(i)
                    if (g.getString("resource") == resource) { val a = g.getJSONArray("capabilities"); for (j in 0 until a.length()) caps.put(a.getString(j)) } }
                caps
            }).put("grants", c.getJSONArray("grants"))
    }
    @Synchronized fun permits(resource: String, capability: String): Boolean {
        val grants = context(resource)?.getJSONArray("grants") ?: return false
        return (0 until grants.length()).any { i -> val g = grants.getJSONObject(i)
            g.getString("resource") == resource && g.getJSONArray("capabilities").let { a -> (0 until a.length()).any { a.getString(it) == capability } } }
    }
    @Synchronized fun logout(): Boolean {
        val old = data.optJSONObject("tokens"); data = JSONObject(); stopSnapshot = emptyMap(); checked.clear(); store.write(null)
        var complete = true
        old?.keys()?.forEach { r -> if (runCatching { request("revoke", mapOf("token" to old.getJSONObject(r).getString("refresh_token"))) }.isFailure) complete = false }
        return complete
    }
}
