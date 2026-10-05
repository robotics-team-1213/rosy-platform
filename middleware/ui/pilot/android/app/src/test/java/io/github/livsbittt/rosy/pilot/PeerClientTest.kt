package io.github.livsbittt.rosy.pilot

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.Executors
import javax.crypto.KeyGenerator

class PeerClientTest {
    private class Memory : PeerVaultStorage {
        val rows = mutableMapOf<String, String>()
        override fun get(id: String) = rows[id]
        override fun endpointKeys() = rows.keys.filterNot { it.startsWith("session|") }.map { it.removePrefix("fence|") }.toSet()
        override fun write(id: String, value: String, remove: Set<String>) { rows[id] = value; remove.forEach { rows.remove(it) } }
    }
    private class Signer : PeerSigner {
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        override val publicKey = PeerProof.encodeKey(key.public)
        override fun sign(context: String, fields: JSONObject) = PeerProof.sign(key.private, context, fields)
    }
    private class Fixture : AutoCloseable {
        val receiver = Signer(); val mobile = Signer(); val memory = Memory()
        private val aes = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val records = PeerRelationshipVault(memory) { aes }
        val ca = HeldCertificate.Builder().certificateAuthority(0).commonName("fixture CA").build()
        val leaf = HeldCertificate.Builder().commonName("robot.local").addSubjectAlternativeName("robot.local").signedBy(ca).build()
        val server = MockWebServer()
        val requests = mutableListOf<RecordedRequest>()
        var approved = true; var corrupt = ""; var statusHold: CountDownLatch? = null; var identityHold: CountDownLatch? = null
        val identityRead = CountDownLatch(1); val statusRead = CountDownLatch(1)
        var candidate: Candidate
        val store = CandidateStore()
        val client: OkHttpClient
        init {
            server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            server.start(); candidate = Candidate("robot.local", server.port, listOf("127.0.0.1"), "Fixture receiver", "rosy_01")
            store.resolved("robot", store.found("robot")!!, candidate)
            client = lobbyClient(candidate).newBuilder().sslSocketFactory(
                HandshakeCertificates.Builder().addTrustedCertificate(ca.certificate).build().sslSocketFactory(),
                HandshakeCertificates.Builder().addTrustedCertificate(ca.certificate).build().trustManager).build()
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    synchronized(requests) { requests.add(request) }
                    val relative = request.path!!.removePrefix("/api/v1/auth/peer-pairing")
                    if (relative == "/identity") {
                        identityRead.countDown(); identityHold?.await(4, TimeUnit.SECONDS)
                        if (corrupt == "identity404") return MockResponse().setResponseCode(404)
                        val key = if (corrupt == "key") Signer().publicKey else receiver.publicKey
                        val offeredCa = when (corrupt) {
                            "other-ca" -> HeldCertificate.Builder().certificateAuthority(0).commonName("wrong CA").build()
                            "expired-ca" -> HeldCertificate.Builder().certificateAuthority(0).commonName("expired CA").validityInterval(0, 1000).build()
                            else -> ca
                        }
                        return json(JSONObject().put("receiver_id", "rosy_01").put("receiver_public_key", key).put("receiver_key_sha256", PeerProof.fingerprint(key))
                            .put("tls_ca_pem", offeredCa.certificatePem()).put("tls_ca_sha256", PeerProof.hash(offeredCa.certificate.encoded)).put("tls_hostname", if (corrupt == "hostname") "other.local" else "robot.local"))
                    }
                    if (relative == "/requests") {
                        assertNull(request.getHeader("Authorization"))
                        val proof = JSONObject(request.body.readUtf8()); val fields = proof.getJSONObject("fields")
                        assertEquals(mobile.publicKey, fields.getString("client_public_key"))
                        PeerProof.verify(mobile.publicKey, "request", fields, proof.getString("signature"))
                        return json(state("pending").put("request_secret", "S".repeat(43)))
                    }
                    if (relative == "/requests/" + "A".repeat(32)) {
                        assertEquals("S".repeat(43), request.getHeader("X-Request-Secret"))
                        assertNull(request.getHeader("Authorization"))
                        statusRead.countDown(); statusHold?.await(4, TimeUnit.SECONDS)
                        return json(state(if (request.method == "DELETE") "cancelled" else if (approved) "approved" else "pending"))
                    }
                    if (relative.endsWith("/challenge")) {
                        if (corrupt == "challenge503") return MockResponse().setResponseCode(503)
                        if (corrupt == "revoked") return MockResponse().setResponseCode(409)
                        val fields = JSONObject().put("relationship_id", "A".repeat(32)).put("challenge_id", "B".repeat(32))
                            .put("nonce", "c".repeat(64)).put("receiver_id", "rosy_01").put("receiver_key_sha256", PeerProof.fingerprint(receiver.publicKey))
                            .put("client_id", mobile.clientId).put("client_key_sha256", PeerProof.fingerprint(mobile.publicKey))
                            .put("role", "operator").put("generation", if (corrupt == "generation") 1 else 0)
                            .put("expires_at", Instant.now().plusSeconds(if (corrupt == "expired") -1 else 60).toString())
                        val signature = receiver.sign("receiver-challenge", fields)
                        if (corrupt == "tampered") fields.put("nonce", "d".repeat(64))
                        return json(JSONObject().put("fields", fields).put("receiver_signature", signature))
                    }
                    if (relative.endsWith("/session")) {
                        assertNull(request.getHeader("Authorization"))
                        val proof = JSONObject(request.body.readUtf8())
                        PeerProof.verify(mobile.publicKey, "session-request", proof.getJSONObject("fields"), proof.getString("signature"))
                        if (corrupt == "session401") return MockResponse().setResponseCode(401)
                        if (corrupt == "retry503" && requests.count { it.path!!.endsWith("/session") } == 1)
                            return MockResponse().setResponseCode(503).setHeader("Retry-After", "0")
                        return json(JSONObject().put("id", "session-fixture").put("token", "fixture-short-session").put("role", "operator").put("expires_at", Instant.now().plusSeconds(3600).toString()))
                    }
                    if (request.path == "/api/v1/auth/whoami") {
                        assertEquals("Bearer fixture-short-session", request.getHeader("Authorization"))
                        if (corrupt == "who401") return MockResponse().setResponseCode(401)
                        return json(JSONObject().put("role", "operator"))
                    }
                    if (request.path == "/api/v1/system/info") return json(JSONObject().put("robot_id", if (corrupt == "robot") "rosy_02" else "rosy_01"))
                    return MockResponse().setResponseCode(404)
                }
            }
        }
        fun state(value: String): JSONObject = JSONObject().put("request_id", "A".repeat(32)).put("state", value).put("revision", if (value == "approved") 1 else 0)
            .put("paired", false).put("display_code", "AB23").put("expires_at", Instant.now().plusSeconds(300).toString()).apply {
                if (value == "approved") { put("relationship_id", "A".repeat(32)); put("generation", 0); put("persistent", true); put("authorization_expires_at", JSONObject.NULL); put("authorization_available", corrupt != "unavailable") }
            }
        fun flow(custom: OkHttpClient = client) = PeerClient(candidate, store, mobile, records, baseClient = custom, pause = {})
        fun saved() = PeerRelationship(PeerRelationshipVault.origin(candidate), "rosy_01", receiver.publicKey, mobile.clientId,
            PeerProof.fingerprint(mobile.publicKey), "A".repeat(32), "operator", 0, true, null)
        fun json(body: JSONObject) = MockResponse().setHeader("Content-Type", "application/json").setBody(body.toString())
        override fun close() { statusHold?.countDown(); identityHold?.countDown(); server.close() }
    }
    @Test fun mintedSessionIsStoredAndReusedUntilNaturalExpiry() {
        Fixture().use { f ->
            val first = f.flow().connect({}, { false })!!
            assertEquals("fixture-short-session", first.target.credential)
            assertNotNull(f.records.readSession(f.candidate))
            f.requests.clear()
            val second = f.flow().connect({ fail("no consent on reuse") }, { fail("no CA on reuse"); false })!!
            assertEquals(first.target.credential, second.target.credential)
            assertTrue(second.authorized())
            assertEquals("rosy_01", second.target.id)
            // 재사용은 새 발급(challenge·session) 없이 whoami·system/info 확인만 한다.
            assertEquals(0, f.requests.count { it.path!!.endsWith("/challenge") || it.path!!.endsWith("/session") })
            assertEquals(2, f.requests.count { it.getHeader("Authorization") != null })
            assertTrue(f.requests.first().path!!.endsWith("/identity"))
        }
    }
    @Test fun storedSessionPastExpiryIsDiscardedAndFreshMintReplacesIt() {
        Fixture().use { f ->
            f.records.remember(f.candidate, f.saved(), f.records.fence(f.candidate))
            f.records.rememberSession(f.candidate, PeerSessionRecord(PeerRelationshipVault.origin(f.candidate),
                "A".repeat(32), "stale-but-long-token-value", "operator", java.time.Instant.now().minusSeconds(1)))
            val session = f.flow().connect({ fail("approval exists") }, { false })!!
            assertEquals("fixture-short-session", session.target.credential)
            assertEquals("fixture-short-session", f.records.readSession(f.candidate)!!.token)
            assertEquals(1, f.requests.count { it.path!!.endsWith("/session") })
        }
    }
    @Test fun realTlsApprovalProofWhoamiIdentityAndDhcpReconnectDoNotReplayCommandsOrPairAgain() {
        Fixture().use { f ->
            val pending = mutableListOf<PeerPending>(); val connected = f.flow().connect({ pending.add(it) }, { false })!!
            assertEquals("rosy_01", connected.target.id); assertTrue(connected.authorized()); assertEquals("AB23", pending.single().code)
            assertTrue(f.records.read(f.candidate)!!.persistent)
            val initial = f.requests.size
            f.store.lost("robot"); val changed = f.candidate.copy(addresses = listOf("127.0.0.1", "127.0.0.2")); f.candidate = changed
            f.store.resolved("robot", f.store.found("robot")!!, changed)
            val rejoined = f.flow().connect({ fail("already approved must not request consent again") }, { false })!!
            assertEquals(connected.target.id, rejoined.target.id)
            assertFalse(f.requests.drop(initial).any { it.path == "/api/v1/auth/peer-pairing/requests" })
            assertTrue(f.requests.all { it.path!!.startsWith("/api/v1/auth/") || it.path == "/api/v1/system/info" })
        }
    }
    @Test fun approvedDecisionSurvivesChallengeFailureAndReconnectDoesNotRepeatReceiverConsent() {
        Fixture().use { f ->
            f.corrupt = "challenge503"
            assertThrows(PeerRefused::class.java) { f.flow().connect({}, { true }) }
            assertNotNull(f.records.read(f.candidate))
            assertEquals(1, f.requests.count { it.path!!.endsWith("/requests") })
            assertEquals(1, f.requests.count { it.path!!.endsWith("/challenge") })
            assertEquals(0, f.requests.count { it.path!!.endsWith("/session") })
            assertTrue(f.requests.none { it.getHeader("Authorization") != null })
            f.corrupt = ""; f.requests.clear()
            assertNotNull(f.flow().connect({ fail("receiver consent repeated") }, { fail("CA match repeated"); false }))
            assertTrue(f.requests.none { it.path!!.contains("/requests") })
            assertEquals(1, f.requests.count { it.path!!.endsWith("/session") })
        }
    }
    @Test fun privateCaCannotIssueSessionUntilActualFingerprintAnswerThenReconnectUsesSavedCa() {
        Fixture().use { f ->
            var compared = false
            val session = f.flow(lobbyClient(f.candidate)).connect({}, { offer ->
                assertEquals(PeerProof.hash(f.ca.certificate.encoded), offer.sha256)
                assertFalse(f.requests.any { it.path!!.endsWith("/session") || it.getHeader("Authorization") != null })
                compared = true; true
            })!!
            assertTrue(compared); assertTrue(session.authorized()); assertEquals(f.ca.certificatePem(), f.records.read(f.candidate)!!.caPem)
            f.flow(lobbyClient(f.candidate)).connect({ fail("saved approval") }, { fail("saved trust"); false })!!
        }
    }
    @Test fun fingerprintMismatchOrInvalidProofNeverSendsBearerOrSession() {
        for (problem in listOf("tampered", "generation", "expired")) Fixture().use { f ->
            f.corrupt = problem
            assertThrows(Exception::class.java) { f.flow().connect({}, { false }) }
            assertFalse(f.requests.any { it.path!!.endsWith("/session") || it.getHeader("Authorization") != null })
        }
        Fixture().use { f ->
            assertThrows(Exception::class.java) { f.flow(lobbyClient(f.candidate)).connect({}, { false }) }
            assertNull(f.records.read(f.candidate)); assertFalse(f.requests.any { it.path!!.endsWith("/session") || it.getHeader("Authorization") != null })
        }
    }
    @Test fun storedReceiverKeyConflictAndRevocationFailClosedWithoutNewConsentAndKeepRecord() {
        for (problem in listOf("key", "revoked", "session401", "who401", "robot")) Fixture().use { f ->
            f.records.remember(f.candidate, f.saved(), f.records.fence(f.candidate)); val before = f.memory.rows.toMap(); f.corrupt = problem
            assertThrows(Exception::class.java) { f.flow().connect({ fail("must not fallback to fresh request") }, { false }) }
            assertNotNull(f.records.read(f.candidate)); assertFalse(f.requests.any { it.path == "/api/v1/auth/peer-pairing/requests" })
            if (problem in listOf("key", "revoked")) assertEquals(before, f.memory.rows)
        }
    }
    @Test fun explicitCancelWithdrawsPendingRequestAndLateApprovalCannotIssueOrPersist() {
        Fixture().use { f ->
            f.approved = false; val flow = f.flow(); val executor = Executors.newSingleThreadExecutor()
            try {
                val result = executor.submit<LobbySession?> { flow.connect({ flow.close() }, { false }) }
                assertThrows(java.util.concurrent.ExecutionException::class.java) { result.get(5, TimeUnit.SECONDS) }
                assertTrue(f.requests.any { it.method == "DELETE" }); assertNull(f.records.read(f.candidate))
                assertFalse(f.requests.any { it.path!!.endsWith("/session") || it.getHeader("Authorization") != null })
            } finally { executor.shutdownNow() }
        }
    }
    @Test fun lossDuringActualHeldIdentityResponseCancelsBeforeRequestAndCannotWriteStaleResult() {
        Fixture().use { f ->
            f.identityHold = CountDownLatch(1); val flow = f.flow(); val executor = Executors.newSingleThreadExecutor()
            try {
                val result = executor.submit<LobbySession?> { flow.connect({}, { false }) }
                assertTrue(f.identityRead.await(3, TimeUnit.SECONDS)); f.store.lost("robot"); f.identityHold!!.countDown()
                assertThrows(java.util.concurrent.ExecutionException::class.java) { result.get(5, TimeUnit.SECONDS) }
                assertEquals(1, f.requests.size); assertTrue(f.memory.rows.isEmpty())
            } finally { flow.close(); executor.shutdownNow() }
        }
    }
    @Test fun verified404KeepsLegacyTrust() {
        Fixture().use { f -> f.corrupt = "identity404"; assertNull(f.flow().connect({}, { false })) }
        Fixture().use { f -> f.corrupt = "identity404"; assertThrows(PeerRefused::class.java) { f.flow(lobbyClient(f.candidate)).connect({}, { false }) } }
    }
    @Test fun privateBootstrapWrongCaOrHostnameCannotCreateRequestOrIssueCredentials() {
        for (problem in listOf("other-ca", "hostname", "expired-ca")) Fixture().use { f ->
            f.corrupt = problem
            assertThrows(Exception::class.java) { f.flow(lobbyClient(f.candidate)).connect({}, { fail("invalid bootstrap cannot request trust"); false }) }
            assertEquals(1, f.requests.size); assertTrue(f.memory.rows.isEmpty())
        }
    }
    @Test fun receiverHistoricalApprovalWithUnavailableAuthorityCannotIssueChallengeOrToken() {
        Fixture().use { f ->
            f.corrupt = "unavailable"
            assertThrows(PeerRefused::class.java) { f.flow().connect({}, { false }) }
            assertFalse(f.requests.any { it.path!!.endsWith("/challenge") || it.path!!.endsWith("/session") || it.getHeader("Authorization") != null })
        }
    }
    @Test fun cancelDuringHeldApprovedResponseCannotIssueOrPersistDespiteServerFinishing() {
        Fixture().use { f ->
            f.statusHold = CountDownLatch(1); val flow = f.flow(); val executor = Executors.newSingleThreadExecutor()
            try {
                val result = executor.submit<LobbySession?> { flow.connect({}, { false }) }
                assertTrue(f.statusRead.await(3, TimeUnit.SECONDS)); flow.close(); f.statusHold!!.countDown()
                assertThrows(java.util.concurrent.ExecutionException::class.java) { result.get(5, TimeUnit.SECONDS) }
                assertTrue(f.requests.any { it.method == "DELETE" }); assertTrue(f.memory.rows.isEmpty())
                assertFalse(f.requests.any { it.path!!.endsWith("/session") || it.getHeader("Authorization") != null })
            } finally { flow.close(); executor.shutdownNow() }
        }
    }
    @Test fun session503CannotReplayProof() {
        Fixture().use { f ->
            f.corrupt = "retry503"
            val outcome = runCatching { f.flow().connect({}, { false }) }
            assertEquals(1, f.requests.count { it.path!!.endsWith("/session") })
            assertTrue(outcome.exceptionOrNull() is PeerRefused)
            assertNotNull(f.records.read(f.candidate))
            assertFalse(f.requests.any { it.getHeader("Authorization") != null })
        }
    }
    @Test fun expiredRememberedApprovalHasZeroNetworkAttemptsAndRemainsStored() {
        Fixture().use { f ->
            f.records.remember(f.candidate, f.saved().copy(persistent = false, authorizationExpiresAt = Instant.EPOCH), f.records.fence(f.candidate))
            val before = f.memory.rows.toMap()
            assertThrows(PeerApprovalExpired::class.java) { f.flow().connect({}, { false }) }
            assertTrue(f.requests.isEmpty()); assertEquals(before, f.memory.rows)
        }
    }
    @Test fun monotonicDeadlineStopsPendingEvenIfWallClockGoesBackwards() {
        Fixture().use { f ->
            f.approved = false; var ticks = 0L
            val flow = PeerClient(f.candidate, f.store, f.mobile, f.records, now = { Instant.EPOCH }, baseClient = f.client,
                pause = { ticks = 301_000_000_000L }, monotonic = { ticks })
            assertThrows(PeerApprovalTimeout::class.java) { flow.connect({}, { false }) }
            assertTrue(f.requests.any { it.method == "DELETE" })
            assertFalse(f.requests.any { it.path!!.endsWith("/session") || it.getHeader("Authorization") != null })
        }
    }
}
