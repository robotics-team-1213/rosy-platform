package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import java.util.concurrent.TimeUnit

class LobbyTest {
    @Test fun legacyServerRequiresCodeAndLearnsIdentityOnlyAfterAuthenticatedPairing() {
        MockWebServer().use { remote ->
            remote.start(); val candidate = row(remote).copy(robotId = ""); val store = store(candidate)
            remote.enqueue(MockResponse().setResponseCode(404))
            val offer = LobbyPairing.offer(candidate)
            assertTrue(offer.legacy); assertEquals("paired", offer.mode)
            assertThrows(IllegalArgumentException::class.java) { LobbyPairing.connect(candidate, offer, store) }
            remote.enqueue(MockResponse().setBody("{\"token\":\"paired-private-token\"}"))
            remote.enqueue(MockResponse().setBody("{\"robot_id\":\"rosy_01\"}"))
            val session = LobbyPairing.connect(candidate, offer, store, "AB123456")
            assertEquals("rosy_01", session.target.id); assertTrue(session.authorized())
            assertEquals("/api/v1/auth/connection", remote.takeRequest()!!.path)
            val pair = remote.takeRequest(); assertEquals("/api/v1/auth/pair", pair!!.path)
            val payload = org.json.JSONObject(pair.body.readUtf8())
            assertEquals("AB123456", payload.getString("code")); assertEquals("Rosy Pilot", payload.getString("label"))
            val identity = remote.takeRequest(); assertEquals("/api/v1/system/info", identity!!.path)
            assertEquals("Bearer paired-private-token", identity.getHeader("Authorization"))
        }
    }
    private fun row(remote: MockWebServer) = Candidate("127.0.0.1", remote.port, listOf("127.0.0.1"), "Test robot", "rosy_01", false)
    private fun store(candidate: Candidate) = CandidateStore().apply {
        resolved("robot", found("robot")!!, candidate)
    }
    @Test fun developmentLobbyConnectsWithoutCodeAndNeverUsesConfigImport() {
        MockWebServer().use { remote ->
            remote.start(); val candidate = row(remote); val store = store(candidate)
            remote.enqueue(MockResponse().setBody("{\"mode\":\"development\",\"robot_id\":\"rosy_01\",\"transport\":\"http\"}"))
            remote.enqueue(MockResponse().setResponseCode(201).setBody("{\"token\":\"session-private-token\",\"role\":\"operator\",\"expires_at\":\"2099-01-01T00:00:00+00:00\"}"))
            val offer = LobbyPairing.offer(candidate)
            val session = LobbyPairing.connect(candidate, offer, store)
            assertTrue(session.authorized()); assertEquals("rosy_01", session.target.id)
            assertEquals("/api/v1/auth/connection", remote.takeRequest(1, TimeUnit.SECONDS)!!.path)
            val join = remote.takeRequest(1, TimeUnit.SECONDS)!!
            assertEquals("/api/v1/auth/development-session", join.path); assertEquals("{}", join.body.readUtf8())
            assertNull(join.getHeader("Authorization"))
        }
    }
    @Test fun pairedLobbyKeepsExistingEightCharacterProtocol() {
        MockWebServer().use { remote ->
            remote.start(); val candidate = row(remote); val store = store(candidate); val offer = LobbyOffer("paired", "rosy_01")
            assertThrows(IllegalArgumentException::class.java) { LobbyPairing.connect(candidate, offer, store) }
            assertThrows(IllegalArgumentException::class.java) { LobbyPairing.connect(candidate, offer, store, "123456") }
            assertThrows(IllegalArgumentException::class.java) { LobbyPairing.connect(candidate, offer, store, "7K2A") }
            remote.enqueue(MockResponse().setBody("{\"token\":\"paired-private-token\"}"))
            val session = LobbyPairing.connect(candidate, offer, store, "7k2a1234")
            assertTrue(session.authorized())
            val payload = org.json.JSONObject(remote.takeRequest(1, TimeUnit.SECONDS)!!.body.readUtf8())
            assertEquals("7K2A1234", payload.getString("code")); assertEquals("Rosy Pilot", payload.getString("label"))
        }
    }
    @Test fun changedHttpAddressRevokesCredentialBeforeAnyFollowupRequest() {
        val store = CandidateStore(); val old = Candidate("robot.local", 8080, listOf("192.0.2.1"), "Test", "rosy_01", false)
        val generation = store.found("robot")!!; store.resolved("robot", generation, old)
        val session = LobbySession(RobotTarget("rosy_01", old.host, old.port, "paired-private-token"), false, java.time.Instant.MAX, old, store)
        assertTrue(session.authorized())
        store.resolved("robot", generation, old.copy(addresses = listOf("192.0.2.2")))
        assertFalse(session.authorized())
        assertThrows(IllegalStateException::class.java) { LobbyPairing.reuse(session) }
    }
    @Test fun advertisementCannotDowngradeTlsOrChangeRobotIdentity() {
        MockWebServer().use { remote ->
            remote.start(); val candidate = row(remote)
            remote.enqueue(MockResponse().setBody("{\"mode\":\"development\",\"robot_id\":\"rosy_01\",\"transport\":\"https\"}"))
            assertThrows(IllegalStateException::class.java) { LobbyPairing.offer(candidate) }
            remote.enqueue(MockResponse().setBody("{\"mode\":\"paired\",\"robot_id\":\"rosy_02\",\"transport\":\"http\"}"))
            assertThrows(IllegalStateException::class.java) { LobbyPairing.offer(candidate) }
        }
    }
    @Test fun pairedTokenIsValidatedAndRevocationDetected() {
        MockWebServer().use { remote ->
            remote.start(); val candidate = row(remote); val store = store(candidate)
            val session = LobbySession(RobotTarget("rosy_01", candidate.host, candidate.port, "paired-private-token"), false, java.time.Instant.MAX, candidate, store)
            remote.enqueue(MockResponse().setBody("{\"role\":\"operator\"}")); assertTrue(LobbyPairing.reuse(session))
            assertEquals("Bearer paired-private-token", remote.takeRequest(1, TimeUnit.SECONDS)!!.getHeader("Authorization"))
            remote.enqueue(MockResponse().setResponseCode(401)); assertFalse(LobbyPairing.reuse(session))
        }
    }
    @Test fun liveTransportAndIdentityChangesInvalidateApproval() {
        val original = Candidate("robot.local", 8080, listOf("192.0.2.1"), "Test", "rosy_01", true)
        val store = store(original)
        val session = LobbySession(RobotTarget("rosy_01", original.host, original.port, "paired-private-token"), true, java.time.Instant.MAX, original, store)
        assertTrue(session.authorized())
        val version = store.found("robot")!!
        store.resolved("robot", version, original.copy(secure = false))
        assertFalse(session.authorized())
        store.resolved("robot", version, original.copy(robotId = "rosy_02"))
        assertFalse(session.authorized())
        val second = store.found("duplicate")!!
        store.resolved("duplicate", second, original)
        assertThrows(IllegalStateException::class.java) { store.addresses(original.host, original.port) }
        store.resolved("robot", version, original.copy(secure = false))
        assertThrows(IllegalStateException::class.java) { store.addresses(original.host, original.port) }
    }
}
