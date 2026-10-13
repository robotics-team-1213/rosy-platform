package io.github.livsbittt.rosy.cam.pairing.peer

import io.github.livsbittt.rosy.cam.pairing.PairableSite
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
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import javax.crypto.KeyGenerator
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import io.github.livsbittt.rosy.cam.link.SiteResolver
import io.github.livsbittt.rosy.cam.link.SiteBrowser
import io.github.livsbittt.rosy.cam.link.SiteSighting
import io.github.livsbittt.rosy.cam.link.CredentialDenied
import kotlinx.coroutines.*

class CameraPeerClientTest {
    private class Memory : CameraVaultStorage {
        val rows = mutableMapOf<String, String>()
        override fun get(id: String) = rows[id]
        override fun endpointKeys() = rows.keys.map { it.removePrefix("fence|") }.toSet()
        override fun write(id: String, value: String, remove: Set<String>) { rows[id] = value; remove.forEach { rows.remove(it) } }
    }
    private class Signer : CameraSigner {
        val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        override val publicKey = CameraProof.encodeKey(key.public)
        override fun sign(context: String, fields: JSONObject) = CameraProof.sign(key.private, context, fields)
    }
    private class Fixture : AutoCloseable {
        val receiver = Signer(); val mobile = Signer(); val memory = Memory()
        val receiverId = "fleet-" + CameraProof.fingerprint(receiver.publicKey).take(32)
        val ca = HeldCertificate.Builder().certificateAuthority(0).commonName("fixture CA").build()
        val leaf = HeldCertificate.Builder().commonName("site.local").addSubjectAlternativeName("site.local").signedBy(ca).build()
        val server = MockWebServer(); val requests = mutableListOf<RecordedRequest>()
        val aes = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val vault = CameraRelationshipVault(memory) { aes }
        var site: PairableSite
        val trusted: OkHttpClient
        var fault = ""; var hold: CountDownLatch? = null; val polled = CountDownLatch(1)
        var challengeHold: CountDownLatch? = null; val challenged = CountDownLatch(1)
        init {
            server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            server.start(java.net.InetAddress.getByName("0.0.0.0"), 0); site = PairableSite("Fixture receiver", "site.local", server.port, "127.0.0.1")
            val trust = HandshakeCertificates.Builder().addTrustedCertificate(ca.certificate).build()
            trusted = cameraPeerHttp(site).newBuilder().sslSocketFactory(trust.sslSocketFactory(), trust.trustManager).build()
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    synchronized(requests) { requests.add(request) }
                    val path = request.path!!.removePrefix("/api/fleet/pairing/v2")
                    if (path == "/identity") {
                        val key = if (fault == "key") Signer().publicKey else receiver.publicKey
                        return json(profile().put("receiver_id", receiverId).put("receiver_public_key", key).put("receiver_key_sha256", CameraProof.fingerprint(key))
                            .put("tls_ca_pem", ca.certificatePem()).put("tls_ca_sha256", CameraProof.hash(ca.certificate.encoded)).put("tls_hostname", "site.local"))
                    }
                    if (path == "/requests") {
                        assertNull(request.getHeader("Authorization"))
                        val proof = JSONObject(request.body.readUtf8()); val fields = proof.getJSONObject("fields")
                        assertEquals(mobile.publicKey, fields.getString("client_public_key")); assertEquals("camera", fields.getString("source_role"))
                        assertFalse(fields.has("role"))
                        CameraProof.verify(mobile.publicKey, "request", fields, proof.getString("signature"))
                        return json(state("pending").put("request_secret", "S".repeat(43)))
                    }
                    if (path.startsWith("/requests/")) {
                        assertEquals("Bearer " + "S".repeat(43), request.getHeader("Authorization"))
                        if (path.endsWith("/cancel")) return json(state("cancelled"))
                        polled.countDown(); hold?.await(5, TimeUnit.SECONDS)
                        return json(state("approved"))
                    }
                    if (path == "/challenge") {
                        challenged.countDown(); challengeHold?.await(5, TimeUnit.SECONDS)
                        assertNull(request.getHeader("Authorization"))
                        val input = JSONObject(request.body.readUtf8()); assertEquals("A".repeat(32), input.getString("relationship_id")); assertEquals(0, input.getInt("generation"))
                        if (fault == "challenge503") return MockResponse().setResponseCode(503)
                        if (fault == "revoked") return MockResponse().setResponseCode(409)
                        val fields = profile().put("relationship_id", "A".repeat(32)).put("challenge_id", "B".repeat(32))
                            .put("nonce", "c".repeat(64)).put("receiver_id", receiverId).put("receiver_key_sha256", CameraProof.fingerprint(receiver.publicKey))
                            .put("client_id", mobile.clientId).put("client_key_sha256", CameraProof.fingerprint(mobile.publicKey))
                            .put("source_id", if (fault == "source") "other_camera" else "ceiling_north").put("generation", if (fault == "generation") 1 else 0)
                            .put("expires_at", Instant.now().plusSeconds(60).toString())
                        if (fault == "audience") fields.put("audience", "core-operator")
                        val signature = receiver.sign("receiver-challenge", fields)
                        if (fault == "signature") fields.put("nonce", "d".repeat(64))
                        return json(JSONObject().put("fields", fields).put("receiver_signature", signature))
                    }
                    if (path == "/session") {
                        assertNull(request.getHeader("Authorization"))
                        val proof = JSONObject(request.body.readUtf8())
                        CameraProof.verify(mobile.publicKey, "session-request", proof.getJSONObject("fields"), proof.getString("signature"))
                        if (fault == "retry503" && requests.count { it.path!!.endsWith("/session") } == 1)
                            return MockResponse().setResponseCode(503).setHeader("Retry-After", "0")
                        return json(profile().put("relationship_id", "A".repeat(32)).put("generation", 0).put("credential_id", "cam-peer-" + "C".repeat(24))
                            .put("token", "fixture-camera-token").put("source_id", if (fault == "issued-source") "other_camera" else "ceiling_north")
                            .put("role", if (fault == "role") "operator" else "overhead-camera").put("expires_at", Instant.now().plusSeconds(3600).toString()))
                    }
                    return MockResponse().setResponseCode(404)
                }
            }
        }
        fun profile() = JSONObject().put("profile", "rosy.camera-peer/1").put("audience", "fleet-camera-ingest")
            .put("device_kind", "overhead-camera").put("source_role", "camera")
        fun state(value: String) = profile().put("request_id", "A".repeat(32)).put("state", value).put("revision", 1).put("credential_issued", false)
            .put("display_code", "AB23").put("expires_at", Instant.now().plusSeconds(300).toString()).apply {
                if (value == "approved") { put("relationship_id", "A".repeat(32)); put("generation", 0); put("source_id", "ceiling_north"); put("persistent", true)
                    put("authorization_expires_at", JSONObject.NULL); put("authorization_available", true) }
            }
        fun flow(client: OkHttpClient = trusted) = CameraPeerClient(site, mobile, vault, baseClient = client, pause = {})
        fun json(row: JSONObject) = MockResponse().setHeader("Content-Type", "application/json").setBody(row.toString())
        override fun close() { hold?.countDown(); challengeHold?.countDown(); server.close() }
    }
    @Test fun approvedSourceSurvivesInterruptionAndDhcp() {
        Fixture().use { f ->
            f.fault = "challenge503"
            assertThrows(PeerRefused::class.java) { f.flow().connect({}, { false }) }
            assertNotNull(f.vault.read(f.site)); assertEquals("ceiling_north", f.vault.read(f.site)!!.sourceId)
            f.fault = ""; f.requests.clear(); f.site = f.site.copy(address = "127.0.0.2")
            // The new address is a current discovery sighting; the fixture listens on all loopback addresses.
            val link = f.flow(cameraPeerHttp(f.site)).connect({ fail("consent repeated") }, { fail("CA repeated"); false }).link
            assertEquals("overhead-camera", link.role); assertEquals("ceiling_north", link.source)
            assertTrue(f.requests.none { it.path!!.contains("/requests") || it.path!!.contains("/overhead/") })
            assertTrue(f.requests.all { it.getHeader("Authorization") == null })
        }
    }
    @Test fun physicalCaMatchPrecedesOperationalProof() {
        Fixture().use { f ->
            assertThrows(IllegalArgumentException::class.java) { f.flow(cameraPeerHttp(f.site)).connect({}, { false }) }
            assertNull(f.vault.read(f.site)); assertEquals(0, f.requests.count { it.path!!.endsWith("/challenge") || it.path!!.endsWith("/session") })
        }
        Fixture().use { f ->
            val result = f.flow(cameraPeerHttp(f.site)).connect({}, { assertEquals(CameraProof.hash(f.ca.certificate.encoded), it.sha256); true })
            assertEquals("ceiling_north", result.link.source)
            assertEquals("site.local", result.link.tlsHost); assertNotNull(result.link.caPin)
        }
    }
    @Test fun signedCameraProfileCannotBecomeAnotherAuthority() {
        for (fault in listOf("audience", "source", "generation", "signature", "role", "issued-source")) Fixture().use { f ->
            f.fault = fault
            assertTrue(fault, runCatching { f.flow().connect({}, { false }) }.isFailure)
            assertNotNull(f.vault.read(f.site))
            if (fault !in listOf("role", "issued-source")) assertEquals(0, f.requests.count { it.path!!.endsWith("/session") })
            assertTrue(f.requests.none { it.path!!.contains("/overhead/") || it.path!!.contains("/api/v1/") })
        }
    }
    @Test fun session503CannotReplayProof() {
        Fixture().use { f ->
            f.fault = "retry503"
            assertThrows(PeerRefused::class.java) { f.flow().connect({}, { false }) }
            assertEquals(1, f.requests.count { it.path!!.endsWith("/session") })
            assertNotNull(f.vault.read(f.site))
        }
    }
    @Test fun cancellationAndForgetCannotSaveLateApproval() {
        for (forget in listOf(false, true)) Fixture().use { f ->
            f.hold = CountDownLatch(1); val flow = f.flow(); val worker = Executors.newSingleThreadExecutor()
            try {
                val result = worker.submit<Boolean> { runCatching { flow.connect({}, { false }) }.isFailure }
                assertTrue(f.polled.await(3, TimeUnit.SECONDS))
                if (forget) f.vault.erase(f.site) else flow.close()
                f.hold!!.countDown(); assertTrue(result.get(4, TimeUnit.SECONDS))
                assertNull(f.vault.read(f.site)); assertEquals(0, f.requests.count { it.path!!.endsWith("/session") })
            } finally { flow.close(); worker.shutdownNow() }
        }
    }
    @Test fun realCredentialProviderUsesSavedProofAndFencesManualReplacement() = runBlocking {
        Fixture().use { f ->
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val file = java.io.File(System.getProperty("java.io.tmpdir"), java.util.UUID.randomUUID().toString() + ".preferences_pb")
            val settings = SettingsStore(PreferenceDataStoreFactory.create(scope = scope) { file })
            val manager = CameraPeerManager(settings, f.vault, f.mobile)
            try {
                val accepted = f.flow().connect({}, { false }); manager.install(accepted, manager.snapshot()) { true }
                val resolver = SiteResolver(accepted.link, SiteBrowser { _, _ -> listOf(SiteSighting("fixture", f.site.tlsHost, f.site.port,
                    listOf(java.net.InetAddress.getByName("127.0.0.1")))) })
                val provider = CameraCredentialProvider(manager, accepted.link, accepted.relationship.id, resolver)
                f.requests.clear()
                val renewed = provider.renew { true }
                assertEquals("ceiling_north", renewed.pairing.source); assertEquals(accepted.link.caPin, renewed.pairing.pin)
                assertEquals(1, f.requests.count { it.path!!.endsWith("/session") }); assertTrue(f.requests.none { it.path!!.contains("/requests") || it.getHeader("Authorization") != null })
                val saved = manager.snapshot()
                f.fault = "revoked"
                assertTrue(runCatching { provider.renew { true } }.exceptionOrNull() is CredentialDenied)
                assertEquals(saved, manager.snapshot()); assertNotNull(f.vault.read(f.site))
                settings.replace(saved.link!!); val before = f.requests.size
                assertTrue(runCatching { provider.renew { true } }.exceptionOrNull() is CredentialDenied)
                assertEquals(before, f.requests.size)
            } finally { scope.cancel() }
        }
    }
    @Test fun canceledRealRenewalCannotIssueOrPersistCredential() = runBlocking {
        Fixture().use { f ->
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val file = java.io.File(System.getProperty("java.io.tmpdir"), java.util.UUID.randomUUID().toString() + ".preferences_pb")
            val settings = SettingsStore(PreferenceDataStoreFactory.create(scope = scope) { file })
            val manager = CameraPeerManager(settings, f.vault, f.mobile)
            try {
                val accepted = f.flow().connect({}, { false }); manager.install(accepted, manager.snapshot()) { true }
                val saved = manager.snapshot(); f.requests.clear(); f.challengeHold = CountDownLatch(1)
                val resolver = SiteResolver(accepted.link, SiteBrowser { _, _ -> listOf(SiteSighting("fixture", f.site.tlsHost, f.site.port,
                    listOf(java.net.InetAddress.getByName("127.0.0.1")))) })
                val provider = CameraCredentialProvider(manager, accepted.link, accepted.relationship.id, resolver)
                val pending = launch(Dispatchers.Default) { provider.renew { isActive } }
                // The initial flow consumed challenged already; wait for the actual second held request.
                withTimeout(3000) { while (f.requests.none { it.path!!.endsWith("/challenge") }) delay(10) }
                pending.cancelAndJoin(); f.challengeHold!!.countDown(); delay(200)
                assertEquals(0, f.requests.count { it.path!!.endsWith("/session") }); assertEquals(saved, manager.snapshot())
                assertNotNull(f.vault.read(f.site))
            } finally { f.challengeHold?.countDown(); scope.cancel() }
        }
    }
}
