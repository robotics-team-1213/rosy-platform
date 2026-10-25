package io.github.livsbittt.rosy.cam.account

import org.junit.Assert.*
import org.junit.Test
import okhttp3.HttpUrl.Companion.toHttpUrl

class AccountSessionTest {
    @Test fun profileIsValidatedRefreshedAndNeverFetchedByCommandAccess() {
        var subject = "alice"; var name = "Alice"; var malformed = false; var calls = 0
        val session = AccountSession(trusted(), MemoryStore(), { endpoint, _ ->
            when (endpoint) {
                "token" -> org.json.JSONObject().put("token_type", "Bearer").put("access_token", signed(1000, subject = subject)).put("refresh_token", "f".repeat(40))
                "introspect" -> org.json.JSONObject().put("active", true).put("sub", subject).put("aud", "site:test")
                "userinfo" -> { calls++; org.json.JSONObject().put("account_id", if (malformed) "other" else subject).put("login", subject).put("display_name", name) }
                else -> org.json.JSONObject()
            }
        }, {1000})
        session.complete(callback(session.begin("site:test")))
        assertEquals("site:test", session.restoredProfileResource())
        assertNotNull(session.access("site:test")); assertTrue(session.permits("site:test", "camera.manage")); assertEquals(0, calls)
        assertEquals("Alice", session.refreshProfile("site:test")!!.getString("display_name"))
        name = "Updated"; assertEquals("Updated", session.refreshProfile("site:test")!!.getString("display_name"))
        assertEquals("https://account.example.test/console/profile", session.context("site:test")!!.getString("profile_url"))
        malformed = true; assertNull(session.refreshProfile("site:test")); assertTrue(session.context("site:test")!!.isNull("profile"))
        malformed = false; name = "x".repeat(81); assertNull(session.refreshProfile("site:test"))
        name = "bad\u007f"; assertNull(session.refreshProfile("site:test"))
        name = "\ud83d\ude00".repeat(80); assertEquals(name, session.refreshProfile("site:test")!!.getString("display_name"))
        name = "bad\ud800"; assertNull(session.refreshProfile("site:test"))
        name = "Alice"; session.refreshProfile("site:test")
        subject = "bob"; session.complete(callback(session.begin("site:test")))
        assertNull(session.profile("site:test")); assertEquals("bob", session.refreshProfile("site:test")!!.getString("account_id"))
        session.logout(); assertNull(session.profile("site:test")); assertNull(session.restoredProfileResource())
    }

    @Test fun stalledProfileNeverBlocksCachedStopAndFailureClearsName() {
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        var stall = false
        val session = AccountSession(trusted(), MemoryStore(), { endpoint, _ ->
            when (endpoint) {
                "token" -> org.json.JSONObject().put("token_type", "Bearer").put("access_token", signed(1000)).put("refresh_token", "f".repeat(40))
                "introspect" -> org.json.JSONObject().put("active", true).put("sub", "alice").put("aud", "site:test")
                "userinfo" -> { if (stall) { entered.countDown(); release.await(); throw java.io.IOException("offline") }
                    org.json.JSONObject().put("account_id", "alice").put("login", "alice").put("display_name", "Alice") }
                else -> org.json.JSONObject()
            }
        }, {1000})
        session.complete(callback(session.begin("site:test"))); session.refreshProfile("site:test"); stall = true
        val worker = java.util.concurrent.Executors.newSingleThreadExecutor()
        try {
            val pending = worker.submit<org.json.JSONObject?> { session.refreshProfile("site:test") }
            assertTrue(entered.await(2, java.util.concurrent.TimeUnit.SECONDS))
            val began = System.nanoTime(); assertNotNull(session.cachedAccess("site:test"))
            assertTrue(System.nanoTime() - began < 100_000_000)
            release.countDown(); assertNull(pending.get(2, java.util.concurrent.TimeUnit.SECONDS)); assertNull(session.profile("site:test"))
        } finally { release.countDown(); worker.shutdownNow() }
    }
    private val privateKey = org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters(java.security.SecureRandom())
    private fun encoded(bytes: ByteArray) = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    private fun signed(now: Long, resource: String = "site:test", subject: String = "alice", capabilities: List<String> = listOf("camera.manage")): String {
        val header = encoded("""{"alg":"Ed25519","typ":"at+jwt","kid":"key"}""".toByteArray())
        val payload = encoded("""{"iss":"https://account.example.test","aud":"$resource","sub":"$subject","sid":"family","jti":"test-jti-123456789","rev":1,"iat":$now,"exp":${now+300},"grants":[{"resource":"$resource","capabilities":${org.json.JSONArray(capabilities)}}]}""".toByteArray())
        val bytes = "$header.$payload".toByteArray()
        val signer = org.bouncycastle.crypto.signers.Ed25519Signer(); signer.init(true, privateKey); signer.update(bytes, 0, bytes.size)
        return "$header.$payload.${encoded(signer.generateSignature())}"
    }
    private fun trusted() = AccountConfig.parse("""{"issuer":"https://account.example.test","client_id":"native-cam","redirect_uri":"https://apps.example.test/cam/callback","resources":["site:test"],"trusted_keys":{"key":"${encoded(privateKey.generatePublicKey().encoded)}"}}""")
    private fun callback(begin: String): String {
        val state = begin.toHttpUrl().queryParameter("state")
        return "https://apps.example.test/cam/callback?code=code&state=$state"
    }
    @Test fun vaultSiteGrantsDoNotRejectCamTokensOrGrantCameraAccess() {
        for (camera in listOf(false, true)) {
            val caps = listOf("vault.read", "vault.operate", "vault.manage") + if (camera) listOf("camera.manage") else emptyList()
            val session = AccountSession(trusted(), MemoryStore(), { endpoint, _ ->
                if (endpoint == "token") org.json.JSONObject().put("token_type", "Bearer")
                    .put("access_token", signed(1000, capabilities = caps)).put("refresh_token", "f".repeat(40))
                else org.json.JSONObject().put("active", true).put("sub", "alice").put("aud", "site:test")
            }, {1000})
            session.complete(callback(session.begin("site:test")))
            assertEquals(camera, session.permits("site:test", "camera.manage"))
            assertTrue(session.permits("site:test", "vault.read"))
            assertFalse(session.permits("site:test", "accounts.manage"))
        }
    }
    @Test fun signedExchangeRefreshAndRevokeUseCurrentIdentity() {
        var now = 1000L; var refreshes = 0; var active = true; val store = MemoryStore()
        val session = AccountSession(trusted(), store, { endpoint, form ->
            when(endpoint) {
                "token" -> { if (form["grant_type"] == "refresh_token") refreshes++
                    org.json.JSONObject().put("token_type", "Bearer").put("access_token", signed(now)).put("refresh_token", "a".repeat(40)) }
                "introspect" -> org.json.JSONObject().put("active", active).put("sub", "alice").put("aud", "site:test")
                else -> org.json.JSONObject()
            }
        }, { now })
        val cb = callback(session.begin("site:test")); session.complete(cb)
        assertThrows(IllegalArgumentException::class.java) { session.complete(cb) }
        assertTrue(session.permits("site:test", "camera.manage"))
        assertFalse(session.permits("site:test", "accounts.manage"))
        now += 320; assertNotNull(session.access("site:test")); assertEquals(1, refreshes)
        active = false; now += 16; assertNull(session.access("site:test"))
        assertTrue(session.logout()); assertNull(store.read())
    }
    @Test fun badSignatureNeverProducesSession() {
        val session = AccountSession(trusted(), MemoryStore(), { _, _ ->
            org.json.JSONObject().put("token_type", "Bearer").put("access_token", signed(1000) + "bad").put("refresh_token", "a".repeat(40))
        }, {1000})
        assertThrows(IllegalArgumentException::class.java) { session.complete(callback(session.begin("site:test"))) }
        assertNull(session.access("site:test"))
    }
    @Test fun pythonAuthorityFixtureIsAccepted() {
        val fixture = org.json.JSONObject(javaClass.getResource("/account-access-v1.json")!!.readText())
        val config = AccountConfig.parse("""{"issuer":"https://account.example.test","client_id":"native-cam","redirect_uri":"https://apps.example.test/cam/callback","resources":["site:test"],"trusted_keys":{"key":"${fixture.getString("public_key")}"}}""")
        val session = AccountSession(config, MemoryStore(), { endpoint, _ ->
            if (endpoint == "token") org.json.JSONObject().put("token_type", "Bearer").put("access_token", fixture.getString("token")).put("refresh_token", "f".repeat(40))
            else org.json.JSONObject().put("active", true).put("sub", "alice").put("aud", "site:test")
        }, {1000})
        session.complete(callback(session.begin("site:test")))
        assertTrue(session.permits("site:test", "camera.manage"))
    }
    @Test fun failedLogoutSurvivesRestartWithoutRestoringIdentity() {
        var online = true; val store = MemoryStore()
        val transport: (String, Map<String,String>) -> org.json.JSONObject = { endpoint, _ ->
            if (!online) throw java.io.IOException("offline")
            if (endpoint == "token") org.json.JSONObject().put("token_type", "Bearer").put("access_token", signed(1000)).put("refresh_token", "f".repeat(40))
            else org.json.JSONObject().put("active", true).put("sub", "alice").put("aud", "site:test")
        }
        val session = AccountSession(trusted(), store, transport, {1000})
        session.complete(callback(session.begin("site:test"))); online = false
        assertFalse(session.logout()); assertNotNull(store.read())
        val reopened = AccountSession(trusted(), store, transport, {1020})
        assertNull(reopened.access("site:test")); online = true
        val retry = AccountSession(trusted(), store, transport, {1040})
        assertTrue(retry.retryRevocations()); assertNull(store.read())
    }
    @Test fun stalledAuthorityCallHasBoundedDeadline() {
        okhttp3.mockwebserver.MockWebServer().use { server ->
            server.enqueue(okhttp3.mockwebserver.MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.NO_RESPONSE))
            server.start(); val client = accountHttpClient(); val began = System.nanoTime()
            try {
                assertEquals(3000, client.callTimeoutMillis)
                assertThrows(java.io.IOException::class.java) { client.newCall(okhttp3.Request.Builder().url(server.url("/stall")).build()).execute().close() }
                assertTrue(java.util.concurrent.TimeUnit.NANOSECONDS.toSeconds(System.nanoTime() - began) < 10)
                assertTrue(10_000 + (2 * 2 + 1) * client.callTimeoutMillis < 30_000)
            } finally { client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll() }
        }
    }
    @Test fun refreshCannotChangeAccountIdentity() {
        var now = 1000L
        val session = AccountSession(trusted(), MemoryStore(), { endpoint, form ->
            if (endpoint == "token") org.json.JSONObject().put("token_type", "Bearer")
                .put("access_token", signed(now, subject = if (form["grant_type"] == "refresh_token") "bob" else "alice"))
                .put("refresh_token", "f".repeat(40))
            else org.json.JSONObject().put("active", true).put("sub", "alice").put("aud", "site:test")
        }, {now})
        session.complete(callback(session.begin("site:test"))); now += 320
        assertNull(session.access("site:test")); assertNull(session.identity("site:test"))
    }
    private fun config() = AccountConfig.parse("""{"issuer":"https://account.example.test","client_id":"native-cam","redirect_uri":"https://apps.example.test/cam/callback","resources":["site:test"],"trusted_keys":{"key":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}}""")
    @Test fun rejectsInsecureIssuerAndWildcardResource() {
        val text = config().issuer
        assertEquals("https://account.example.test", text)
        assertThrows(IllegalArgumentException::class.java) { AccountConfig.parse("""{"issuer":"http://example.test"}""") }
    }
    @Test fun pkceStateSingleUseAndExactCallback() {
        val store = MemoryStore()
        val session = AccountSession(config(), store, { _, _ -> error("unexpected network") })
        val first = session.begin("site:test")
        assertTrue(first.contains("code_challenge_method=S256"))
        assertFalse(first.contains("code_verifier"))
        assertThrows(IllegalArgumentException::class.java) { session.complete("https://evil.example/cam/callback?code=x&state=x") }
        assertThrows(IllegalArgumentException::class.java) { session.begin("site:other") }
    }
    @Test fun missingSessionNeverFallsBackToMachineCredential() {
        val session = AccountSession(config(), MemoryStore(), { _, _ -> error("unexpected network") })
        assertNull(session.access("site:test"))
        assertFalse(session.permits("site:test", "camera.manage"))
    }
}
class MemoryStore : AccountStore {
    private var value: String? = null
    override fun read() = value
    override fun write(value: String?) { this.value = value }
}
