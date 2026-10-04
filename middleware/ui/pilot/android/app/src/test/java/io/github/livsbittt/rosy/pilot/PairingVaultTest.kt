package io.github.livsbittt.rosy.pilot

import java.time.Instant
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate

class PairingVaultTest {
    private class Memory : VaultStorage {
        val rows = mutableMapOf<String, String>()
        override fun get(id: String) = rows[id]
        override fun write(id: String, value: String, remove: Set<String>) { rows[id] = value; remove.forEach { rows.remove(it) } }
    }
    private val memory = Memory()
    private val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    private var clock = Instant.parse("2026-01-01T00:00:00Z")
    private val vault = PairingVault(memory, { key }, { clock })
    private val first = Candidate("robot.local", 443, listOf("192.168.1.10"), "Robot", "rosy_01", true)
    private val offer = LobbyOffer("paired", "rosy_01")
    private fun store(c: Candidate) = CandidateStore().apply { resolved("robot", found("robot")!!, c) }
    private fun save(c: Candidate = first) = vault.saveVerified(c,
        LobbySession(RobotTarget("rosy_01", c.host, c.port, "private-token"), c.secure, Instant.parse("2099-01-01T00:00:00Z"), c, store(c)))
    private fun seedLegacy(c: Candidate = first) {
        val row = JSONObject().put("robot_id", "rosy_01").put("credential", "old-private-token").put("expires_at", "2099-01-01T00:00:00Z")
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
        memory.rows[vault.legacySlot(c)] = Base64.getEncoder().encodeToString(cipher.iv + cipher.doFinal(row.toString().toByteArray(Charsets.UTF_8)))
    }
    @Test fun httpsRecordSurvivesAddressChangeButLiveSessionStillUsesFreshSelection() {
        save(); val changed = first.copy(addresses = listOf("192.168.1.20")); val fresh = store(changed)
        val login = vault.inspect(changed, offer, fresh)
        assertEquals(SavedLoginStatus.READY, login.status); assertTrue(login.session!!.authorized())
        assertEquals("private-token", login.session.target.credential)
        fresh.clear(); assertFalse(login.session.authorized()); assertEquals(1, memory.rows.size)
    }
    @Test fun expiredLoginIsRetainedWithoutExtendingItsExpiry() {
        save(); val bytes = memory.rows.toMap(); clock = Instant.parse("2100-01-01T00:00:00Z")
        val result = vault.inspect(first, offer, store(first))
        assertEquals(SavedLoginStatus.EXPIRED, result.status); assertNull(result.session); assertEquals(bytes, memory.rows)
    }
    @Test fun absentAndConflictingDiscoveryDoNotEraseApprovalMemory() {
        save(); val bytes = memory.rows.toMap()
        assertEquals(SavedLoginStatus.UNAVAILABLE, vault.inspect(first, offer, CandidateStore()).status)
        val conflict = store(first); conflict.resolved("other", conflict.found("other")!!, first.copy(robotId = "rosy_02"))
        assertEquals(SavedLoginStatus.UNAVAILABLE, vault.inspect(first, offer, conflict).status)
        assertEquals(bytes, memory.rows)
    }
    @Test fun malformedCiphertextAndUnavailableKeyDoNotEraseStoredBytes() {
        save(); val id = memory.rows.keys.single(); memory.rows[id] = "malformed"
        assertEquals(SavedLoginStatus.UNAVAILABLE, vault.inspect(first, offer, store(first)).status)
        assertEquals("malformed", memory.rows[id])
        save(); val bytes = memory.rows.toMap(); val locked = PairingVault(memory, { throw IllegalStateException("locked") })
        assertNull(locked.load(first, offer, store(first))); assertEquals(bytes, memory.rows)
    }
    @Test fun plaintextAddressChangeNeverFindsTheSavedBearer() {
        val http = first.copy(secure = false); save(http)
        assertNotNull(vault.load(http, offer, store(http)))
        val changed = http.copy(addresses = listOf("192.168.1.20"))
        assertEquals(SavedLoginStatus.NONE, vault.inspect(changed, offer, store(changed)).status)
        assertEquals(1, memory.rows.size)
    }
    @Test fun oldSlotOnlyMigratesAfterCallerVerifiesAndSavesTheSession() {
        seedLegacy(); val bytes = memory.rows.toMap()
        val old = vault.load(first, offer, store(first))!!; assertEquals(bytes, memory.rows)
        val changed = first.copy(addresses = listOf("192.168.1.20"))
        assertNull(vault.load(changed, offer, store(changed)))
        vault.saveVerified(first, old)
        assertFalse(memory.rows.containsKey(vault.legacySlot(first))); assertEquals(1, memory.rows.size)
        assertEquals("old-private-token", vault.load(changed, offer, store(changed))!!.target.credential)
    }
    @Test fun explicitForgetRemovesSelectedStableAndLegacyRecordsOnly() {
        save(); seedLegacy(); val other = first.copy(host = "other.local", robotId = "rosy_01"); save(other)
        vault.erase(first)
        assertNull(vault.load(first, offer, store(first))); assertNotNull(vault.load(other, offer, store(other)))
        assertEquals(2, memory.rows.size) // Other credential and local forget fence.
    }
    @Test fun ciphertextCopiedToAnotherOriginCannotAuthorizeIt() {
        save(); val encrypted = memory.rows.values.single(); val other = first.copy(host = "other.local"); save(other)
        memory.rows.keys.filter { it != memory.rows.keys.first() }.forEach { memory.rows[it] = encrypted }
        assertEquals(SavedLoginStatus.UNAVAILABLE, vault.inspect(other, offer, store(other)).status)
    }
    @Test fun storedHttpsLoginNeverBypassesDefaultTlsTrustOrSendsBearerBeforeHandshake() {
        MockWebServer().use { remote ->
            val cert = HeldCertificate.Builder().addSubjectAlternativeName("robot.local").build()
            remote.useHttps(HandshakeCertificates.Builder().heldCertificate(cert).build().sslSocketFactory(), false); remote.start()
            val c = first.copy(port = remote.port, addresses = listOf("127.0.0.1")); save(c)
            val bytes = memory.rows.toMap(); val session = vault.load(c, offer, store(c))!!
            assertThrows(java.io.IOException::class.java) { LobbyPairing.reuse(session) }
            assertEquals(0, remote.requestCount); assertEquals(bytes, memory.rows)
        }
    }
    @Test fun verifiedRejectionAndActualTimeoutDoNotForgetStoredLogin() {
        MockWebServer().use { remote ->
            remote.start(); val c = first.copy(host = "127.0.0.1", port = remote.port, addresses = listOf("127.0.0.1"), secure = false)
            save(c); val bytes = memory.rows.toMap(); val session = vault.load(c, offer, store(c))!!
            remote.enqueue(okhttp3.mockwebserver.MockResponse().setResponseCode(401))
            assertFalse(LobbyPairing.reuse(session)); assertEquals(bytes, memory.rows)
            remote.enqueue(okhttp3.mockwebserver.MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.NO_RESPONSE))
            assertThrows(java.io.IOException::class.java) { LobbyPairing.reuse(session) }
            assertEquals(bytes, memory.rows); assertEquals(2, remote.requestCount)
        }
    }
    @Test fun localForgetCompletesAfterCloseEvenWhenUiGenerationWasSuperseded() {
        class Queue : java.util.concurrent.Executor {
            val work = ArrayDeque<Runnable>()
            override fun execute(command: Runnable) { work.add(command) }
            fun next() = work.removeFirst().run()
        }
        save(); val io = Queue(); val ui = Queue(); var attempt = 1; var resumed = false; val order = mutableListOf<String>()
        SessionShutdown.close(io, ui, {
            order.add("zero-and-close"); vault.erase(first); order.add("forgotten")
        }, { if (attempt == 1) resumed = true })
        attempt = 2; assertEquals(1, memory.rows.size)
        io.next(); assertNull(vault.load(first, offer, store(first))); assertEquals(listOf("zero-and-close", "forgotten"), order)
        ui.next(); io.next(); ui.next(); assertFalse(resumed)
    }

    @Test fun forgetFencePreventsOrphanOldIpFromResurrectingButFreshLoginCanReplaceIt() {
        seedLegacy(); val changed = first.copy(addresses = listOf("192.168.1.20"))
        vault.erase(changed)
        assertNull(vault.load(first, offer, store(first))) // Cannot identify old ciphertext by hostname; fence it.
        assertTrue(memory.rows.containsKey(vault.legacySlot(first)))
        save(changed)
        assertEquals("private-token", vault.load(first, offer, store(first))!!.target.credential)
    }

}
