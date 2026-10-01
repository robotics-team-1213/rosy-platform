package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.link.certPin
import io.github.livsbittt.rosy.cam.settings.SiteLink
import io.github.livsbittt.rosy.cam.ui.PairingText
import io.github.livsbittt.rosy.cam.R
import java.net.InetAddress
import java.nio.charset.StandardCharsets.UTF_8
import java.security.cert.CertificateException
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * The HTTP transport against a MockWebServer that plays the S2 routes over real TLS (rosy-00 a83653e3 + 920bef4d):
 * the URL is `tls_host`, TCP goes to 127.0.0.1, and the certificate has no IP SAN.
 */
class PairingHttpTest {
    private val ca = HeldCertificate.Builder().certificateAuthority(0).commonName("Rosy test site CA").build()
    private val leaf = HeldCertificate.Builder().signedBy(ca).addSubjectAlternativeName(HOST).build()
    private val servers = mutableListOf<MockWebServer>()

    @After
    fun tearDown() {
        servers.forEach { it.shutdown() }
    }

    private fun refusal(status: Int, code: String, retryAfter: String? = null): MockResponse =
        MockResponse().setResponseCode(status)
            .setBody("""{"detail":{"code":"$code","message":"refused"}}""")
            .apply { if (retryAfter != null) setHeader("Retry-After", retryAfter) }

    /** S2 in miniature: one request id, commit-reveal, code from its served leaf, one delivery, confirm. */
    private inner class Fleet : Dispatcher() {
        val requestId = "pr-abcDEF0123456789"
        val serverNonce = Pairing.newSecret()
        val token = Pairing.newSecret()
        var credentialId = "cred-0a1b2c3d4e5f"
        var state = "none"
        var commit: String? = null
        var pollDigest: String? = null
        var code: String? = null
        var confirmed = false
        val forced = mutableMapOf<String, MockResponse>()
        val routes = CopyOnWriteArrayList<String>()
        val recorded = CopyOnWriteArrayList<RecordedRequest>()

        fun approve(typed: String): Boolean = (typed == code).also { if (it) state = "approved" }

        private fun json(status: Int, body: JSONObject) = MockResponse().setResponseCode(status).setBody(body.toString())

        private fun authorized(request: RecordedRequest): Boolean =
            request.getHeader("Authorization")?.removePrefix("Bearer ")?.let { Pairing.sha256Text(it) } == pollDigest

        override fun dispatch(request: RecordedRequest): MockResponse {
            recorded += request
            val path = request.requestUrl!!.encodedPath
            val route = when {
                request.method == "POST" && path == "$BASE/requests" -> "request"
                request.method == "POST" && path == "$BASE/requests/$requestId/reveal" -> "reveal"
                request.method == "POST" && path == "$BASE/requests/$requestId/confirm" -> "confirm"
                request.method == "GET" && path == "$BASE/requests/$requestId" -> "poll"
                else -> "other"
            }
            routes += route
            forced.remove(route)?.let { return it }
            val body = request.body.readUtf8()
            return when (route) {
                "request" -> {
                    if (PairingRequest.validate(body.toByteArray(UTF_8)) != null) return refusal(400, "PAIRING_REQUEST_INVALID")
                    val json = JSONObject(body)
                    commit = json.getString("client_commit")
                    pollDigest = json.getString("poll_secret_sha256")
                    state = "pending"
                    json(201, JSONObject().put("request_id", requestId).put("server_nonce", serverNonce).put("expires_at", "2099-01-01T00:00:00Z"))
                }
                "reveal" -> {
                    if (!authorized(request)) return refusal(401, "POLL_SECRET_INVALID")
                    val nonce = JSONObject(body).getString("client_nonce")
                    if (Pairing.commit(nonce) != commit) return refusal(400, "COMMIT_MISMATCH")
                    code = Pairing.confirmationCode(Pairing.ROLE, requestId, Pairing.derSha256(leaf.certificate.encoded), nonce, serverNonce)
                    state = "revealed"
                    json(200, JSONObject().put("state", "revealed"))
                }
                "poll" -> when {
                    !authorized(request) -> refusal(401, "POLL_SECRET_INVALID")
                    state == "delivered" -> refusal(410, "PAIRING_RESULT_GONE")
                    state != "approved" -> json(200, JSONObject().put("state", state))
                    else -> {
                        state = "delivered"
                        json(200, JSONObject().put("state", "approved").put("result", result())).setHeader("Cache-Control", "no-store")
                    }
                }
                "confirm" -> {
                    if (!authorized(request)) return refusal(401, "POLL_SECRET_INVALID")
                    val id = JSONObject(body).optString("credential_id")
                    if (!Regex("^[A-Za-z0-9_-]{1,64}$").matches(id)) return refusal(400, "PAIRING_CONFIRM_INVALID")
                    if (state != "delivered") return refusal(409, "NOT_DELIVERED")
                    if (id != credentialId) return refusal(409, "CREDENTIAL_MISMATCH")
                    confirmed = true
                    state = "confirmed"
                    json(200, JSONObject().put("state", "confirmed").put("credential_id", id))
                }
                else -> refusal(404, "UNKNOWN_PAIRING_REQUEST")
            }
        }

        fun result(): JSONObject = JSONObject().put("proto", "rosy-pair/1").put("role", "overhead-camera")
            .put("site_name", "Rosy Lab").put("source_id", "ceiling_north").put("tls_host", HOST)
            .put("site_ca_pem", ca.certificatePem()).put("token", token).put("credential_id", credentialId)
            .put("expires_at", "2027-03-30T00:00:00Z")
    }

    private class Store : PairingLinkStore {
        var saved: SiteLink? = null
        val events = mutableListOf<String>()
        override fun save(link: SiteLink) { saved = link; events += "save" }
        override fun discard(link: SiteLink) { saved = null; events += "discard" }
    }

    private fun serve(fleet: Fleet): PairableSite {
        val certs = HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build()
        val server = MockWebServer().also {
            it.useHttps(certs.sslSocketFactory(), false)
            it.dispatcher = fleet
            it.start(InetAddress.getByName(LOOPBACK), 0)
            servers += it
        }
        return PairableSite("Rosy Lab", HOST, server.port, LOOPBACK)
    }

    private val store = Store()

    private fun client(site: PairableSite) = PairingClient(HttpPairingTransport(site), "Galaxy S21 ceiling", "0.4.0", store)

    @Test
    fun wholeFlowOverTls() {
        val fleet = Fleet()
        val site = serve(fleet)
        val pairing = client(site)
        val requested = pairing.start(site) as PairingState.Requested
        assertEquals("the phone's code is the site's code", fleet.code, requested.code)
        assertTrue(pairing.poll() is PairingState.AwaitingApproval)
        assertTrue(fleet.approve(requested.code))
        val shown = pairing.poll() as PairingState.ConfirmFingerprint
        assertEquals(Pairing.siteFingerprint(ca.certificatePem()), shown.fingerprint)
        assertNull(store.saved)
        val link = (pairing.answerFingerprint(true) as PairingState.Paired).link
        assertTrue(fleet.confirmed)
        assertEquals(link, store.saved)
        assertNull(SiteLink.validate(link))
        assertEquals(HOST, link.tlsHost)
        assertEquals(site.port, link.port)
        assertEquals(certPin(ca.certificate.encoded), link.caPin)
        assertEquals(fleet.token, link.token)
        assertEquals("cred-0a1b2c3d4e5f", link.credentialId)
        assertEquals("2027-03-30T00:00:00Z", link.expiresAt)
        assertNull("the resolved IP is not stored", link.manualHost)

        assertEquals(listOf("other", "request", "reveal", "poll", "poll", "confirm"), fleet.routes)
        val byRoute = fleet.routes.zip(fleet.recorded).toMap()
        assertNull("the request carries no bearer", byRoute.getValue("request").getHeader("Authorization"))
        for (route in listOf("reveal", "poll", "confirm")) {
            assertTrue(route, byRoute.getValue(route).getHeader("Authorization")!!.startsWith("Bearer "))
        }
        // MockWebServer's requestUrl names its own host; the Host header is what the phone dialled.
        val request = byRoute.getValue("request")
        assertEquals("$HOST:${site.port}", request.getHeader("Host") ?: request.getHeader(":authority"))
        assertTrue(byRoute.getValue("request").getHeader("Content-Type")!!.startsWith("application/json"))
    }

    @Test
    fun aResultWithAnInvalidCredentialIdIsNeitherStoredNorConfirmed() {
        // rosy-00 920bef4d: confirm accepts ^[A-Za-z0-9_-]{1,64}$ only; the phone checks it first.
        for (bad in listOf("cred/../x", "cred 1", "c".repeat(65), "")) {
            val fleet = Fleet().apply { credentialId = bad }
            val site = serve(fleet)
            val pairing = client(site)
            fleet.approve((pairing.start(site) as PairingState.Requested).code)
            assertEquals(bad, PairingState.Rejected("bad_value"), pairing.poll())
            assertNull(store.saved)
            assertFalse(fleet.routes.contains("confirm"))
            assertEquals(R.string.pairing_failed_result, PairingText.failure(pairing.state))
        }
    }

    /** One S2 refusal per row: the route it hits, and the state the client ends in. */
    private data class Row(val route: String, val response: MockResponse, val expected: PairingState, val text: Int)

    @Test
    fun everyS2RefusalMapsToAState() {
        val rows = listOf(
            Row("request", refusal(400, "PAIRING_REQUEST_INVALID"), PairingState.Rejected("pairing_request_invalid"), R.string.pairing_failed_other),
            Row("request", refusal(429, "PAIRING_RATE_LIMITED", "30"), PairingState.Rejected("busy"), R.string.pairing_failed_busy),
            Row("request", refusal(429, "PAIRING_PENDING_FULL", "10"), PairingState.Rejected("busy"), R.string.pairing_failed_busy),
            Row("reveal", refusal(400, "COMMIT_MISMATCH"), PairingState.Rejected("commit_mismatch"), R.string.pairing_failed_other),
            Row("reveal", refusal(409, "ALREADY_REVEALED"), PairingState.Rejected("already_revealed"), R.string.pairing_failed_other),
            Row("reveal", refusal(410, "PAIRING_REQUEST_CLOSED"), PairingState.Expired("gone"), R.string.pairing_failed_expired),
            Row("poll", refusal(401, "POLL_SECRET_INVALID"), PairingState.Rejected("poll_secret"), R.string.pairing_failed_other),
            Row("poll", refusal(410, "PAIRING_RESULT_GONE"), PairingState.Expired("gone"), R.string.pairing_failed_expired),
            Row("poll", refusal(404, "UNKNOWN_PAIRING_REQUEST"), PairingState.Expired("unknown_request"), R.string.pairing_failed_unknown_request),
            // After confirm is sent the credential may be active: confirm_* reasons keep its id and ask for a revoke.
            Row("confirm", refusal(409, "NOT_DELIVERED"), PairingState.Rejected("confirm_not_delivered", CRED), R.string.pairing_failed_revoke),
            Row("confirm", refusal(409, "CREDENTIAL_MISMATCH"), PairingState.Rejected("confirm_credential_mismatch", CRED), R.string.pairing_failed_revoke),
            Row("confirm", refusal(410, "PAIRING_REQUEST_CLOSED"), PairingState.Expired("confirm_gone", CRED), R.string.pairing_failed_revoke),
            Row("confirm", refusal(400, "PAIRING_CONFIRM_INVALID"), PairingState.Rejected("confirm_pairing_confirm_invalid", CRED), R.string.pairing_failed_revoke),
            Row("confirm", MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST), PairingState.Rejected(PairingClient.CONFIRM_UNANSWERED, CRED), R.string.pairing_failed_unanswered),
        )
        for (row in rows) {
            val fleet = Fleet()
            val site = serve(fleet)
            store.saved = null
            store.events.clear()
            val pairing = client(site)
            fleet.forced[row.route] = row.response
            val final = when (row.route) {
                "request", "reveal" -> pairing.start(site)
                "poll" -> pairing.start(site).let { pairing.poll() }
                else -> {
                    fleet.approve((pairing.start(site) as PairingState.Requested).code)
                    pairing.poll()
                    pairing.answerFingerprint(true)
                }
            }
            val label = "${row.route} ${row.response.status}"
            assertEquals(label, row.expected, final)
            assertEquals(label, row.text, PairingText.failure(final))
            val arg = PairingText.failureArg(final)
            if (row.text == R.string.pairing_failed_unanswered) assertEquals(label, CRED, arg)
            assertNull("$label: nothing stays stored", store.saved)
            if (row.route == "confirm") assertEquals(label, listOf("save", "discard"), store.events)
        }
    }

    @Test
    fun pollTooFastKeepsTheStateAndHandsBackRetryAfter() {
        val fleet = Fleet()
        val site = serve(fleet)
        val pairing = client(site)
        val requested = pairing.start(site)
        fleet.forced["poll"] = refusal(429, "POLL_TOO_FAST", "2")
        assertEquals(requested, pairing.poll())
        assertEquals(2L, pairing.retryAfterS)
    }

    @Test
    fun theSessionPollsEveryTwoSecondsAndHonoursRetryAfter() = runBlocking {
        val fleet = Fleet()
        val site = serve(fleet)
        val pairing = client(site)
        val waits = mutableListOf<Long>()
        val session = PairingSession(pairing, this, Dispatchers.IO) { ms ->
            waits += ms
            when (waits.size) {
                1 -> fleet.forced["poll"] = refusal(429, "POLL_TOO_FAST", "5")
                3 -> fleet.approve(fleet.code!!)
            }
        }
        session.start(site)
        session.join()
        assertTrue(session.state.value is PairingState.ConfirmFingerprint)
        assertEquals(listOf(2_000L, 5_000L, 2_000L), waits)
        session.answer(true)
        session.join()
        assertTrue(session.state.value is PairingState.Paired)
    }

    @Test
    fun noDiscoveredAddressMeansNoConnection() = runBlocking {
        val fleet = Fleet()
        val site = serve(fleet).copy(address = null)
        val session = PairingSession(client(site), this, Dispatchers.IO) { }
        session.start(site)
        session.join()
        assertEquals(PairingState.Rejected("unreachable"), session.state.value)
        assertTrue(fleet.routes.isEmpty())
    }

    @Test
    fun aDifferentLeafLaterInTheSessionIsRefused() {
        val trust = FirstContactTrust()
        val other = HeldCertificate.Builder().signedBy(ca).addSubjectAlternativeName(HOST).build()
        trust.checkServerTrusted(arrayOf(leaf.certificate, ca.certificate), "ECDHE_ECDSA")
        trust.checkServerTrusted(arrayOf(leaf.certificate), "ECDHE_ECDSA")
        try {
            trust.checkServerTrusted(arrayOf(other.certificate, ca.certificate), "ECDHE_ECDSA")
            fail("a second leaf must not be trusted")
        } catch (e: CertificateException) {
            assertEquals(PairingSession.LEAF_CHANGED, PairingSession.networkReason(java.io.IOException(e)))
        }
        assertEquals(leaf.certificate, trust.leaf)
        assertNotEquals("unreachable", PairingSession.networkReason(CertificateException(FirstContactTrust.LEAF_CHANGED)))
    }

    @Test
    fun errorCodesFromFastApiAndBareBodies() {
        assertEquals("CODE_MISMATCH", HttpPairingTransport.errorCode("""{"detail":{"code":"CODE_MISMATCH"}}""".toByteArray()))
        assertEquals("X", HttpPairingTransport.errorCode("""{"code":"X"}""".toByteArray()))
        assertNull(HttpPairingTransport.errorCode("""{"detail":[{"loc":["body"]}]}""".toByteArray()))
        assertNull(HttpPairingTransport.errorCode("<html>".toByteArray()))
    }

    @Test
    fun pollIntervalIsTwoSecondsOrRetryAfter() {
        assertEquals(2_000L, PairingSession.nextPollDelayMs(null))
        assertEquals(2_000L, PairingSession.nextPollDelayMs(1))
        assertEquals(30_000L, PairingSession.nextPollDelayMs(30))
    }

    private companion object {
        const val HOST = "fixture-site.local"
        const val CRED = "cred-0a1b2c3d4e5f"
        const val LOOPBACK = "127.0.0.1"
        const val BASE = HttpPairingTransport.BASE
    }
}
