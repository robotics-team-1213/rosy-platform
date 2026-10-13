package io.github.livsbittt.rosy.cam.account

import org.junit.Assert.*
import org.junit.Test

class AccountSessionTest {
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
