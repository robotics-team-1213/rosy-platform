package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.link.certPin
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.nio.charset.StandardCharsets.UTF_8
import java.security.cert.X509Certificate
import java.time.Instant
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The rosy-pair/1 client flow over a fake transport that plays a small S2 server (a83653e3 behaviour). */
class PairingClientTest {
    private val host = "fixture-site.local"
    private val site = PairableSite("Rosy Lab", host, 8443)
    private val ca = HeldCertificate.Builder().certificateAuthority(0).commonName("Rosy test site CA").build()
    private val leaf = HeldCertificate.Builder().signedBy(ca).addSubjectAlternativeName(host).build()

    /** Minimal S2: commit-reveal, code from its own leaf, one-time result, confirm. */
    private inner class FakeSite(
        val servedLeaf: X509Certificate = leaf.certificate,
        val serverLeaf: X509Certificate = leaf.certificate,
        val caPem: String = ca.certificatePem(),
    ) : PairingTransport {
        val requestId = "pr-test_0123456789"
        val serverNonce = Pairing.newSecret()
        val token = Pairing.newSecret()
        val credentialId = "cred-0a1b2c3d4e5f"
        var state = "pending"
        var commit: String? = null
        var pollDigest: String? = null
        var code: String? = null
        val sent = mutableListOf<String>()
        var refuseNext: PairingRefused? = null
        var confirmed = false

        override fun firstContactLeaf(site: PairableSite): X509Certificate = servedLeaf

        private fun refuse() = refuseNext?.let { refuseNext = null; throw it }

        override fun request(site: PairableSite, body: ByteArray): ByteArray {
            sent += String(body, UTF_8)
            refuse()
            assertNull(PairingRequest.validate(body))
            val json = JSONObject(String(body, UTF_8))
            commit = json.getString("client_commit")
            pollDigest = json.getString("poll_secret_sha256")
            return JSONObject().put("request_id", requestId).put("server_nonce", serverNonce)
                .put("expires_at", "2026-10-01T00:05:00Z").toString().toByteArray(UTF_8)
        }

        override fun reveal(site: PairableSite, requestId: String, pollSecret: String, body: ByteArray): ByteArray {
            sent += String(body, UTF_8)
            refuse()
            assertEquals(pollDigest, Pairing.sha256Text(pollSecret))
            val nonce = JSONObject(String(body, UTF_8)).getString("client_nonce")
            if (Pairing.commit(nonce) != commit) throw PairingRefused(400, "COMMIT_MISMATCH")
            code = Pairing.confirmationCode(Pairing.ROLE, requestId, Pairing.derSha256(serverLeaf.encoded), nonce, serverNonce)
            state = "revealed"
            return """{"state":"revealed"}""".toByteArray()
        }

        /** The operator types [typed] into the console (D-341 3). */
        fun approve(typed: String): Boolean {
            if (typed != code) return false
            state = "approved"
            return true
        }

        fun result(): JSONObject = JSONObject().put("proto", "rosy-pair/1").put("role", "overhead-camera")
            .put("site_name", "Rosy Lab").put("source_id", "ceiling_north").put("tls_host", host)
            .put("site_ca_pem", caPem).put("token", token).put("credential_id", credentialId)
            .put("expires_at", "2027-03-30T00:00:00Z")

        override fun poll(site: PairableSite, requestId: String, pollSecret: String): ByteArray {
            refuse()
            if (Pairing.sha256Text(pollSecret) != pollDigest) throw PairingRefused(401, "POLL_SECRET_INVALID")
            if (state == "delivered") throw PairingRefused(410, "PAIRING_RESULT_GONE")
            if (state != "approved") return JSONObject().put("state", state).toString().toByteArray(UTF_8)
            state = "delivered"
            return JSONObject().put("state", "approved").put("result", result()).toString().toByteArray(UTF_8)
        }

        override fun confirm(site: PairableSite, requestId: String, pollSecret: String, body: ByteArray): ByteArray {
            refuse()
            val id = JSONObject(String(body, UTF_8)).getString("credential_id")
            if (state != "delivered") throw PairingRefused(409, "NOT_DELIVERED")
            if (id != credentialId) throw PairingRefused(409, "CREDENTIAL_MISMATCH")
            confirmed = true
            state = "confirmed"
            return JSONObject().put("state", "confirmed").put("credential_id", id).toString().toByteArray(UTF_8)
        }
    }

    private class Store : PairingLinkStore {
        var saved: SiteLink? = null
        val events = mutableListOf<String>()

        override fun save(link: SiteLink) {
            saved = link
            events += "save"
        }

        override fun discard(link: SiteLink) {
            saved = null
            events += "discard"
        }
    }

    private var clock = Instant.parse("2026-10-01T00:00:00Z")
    private val store = Store()

    private fun client(fake: FakeSite) =
        PairingClient(fake, "Galaxy S21 ceiling", "0.4.0", store, now = { clock })

    /** Start, operator types the phone's code, poll to the fingerprint step. */
    private fun toFingerprint(fake: FakeSite, pairing: PairingClient): PairingState.ConfirmFingerprint {
        val requested = pairing.start(site) as PairingState.Requested
        assertTrue(fake.approve(requested.code))
        return pairing.poll() as PairingState.ConfirmFingerprint
    }

    @Test
    fun happyPathStoresAValidSiteLinkAfterConfirm() {
        val fake = FakeSite()
        val pairing = client(fake)
        val requested = pairing.start(site) as PairingState.Requested
        assertEquals(fake.code, requested.code)
        assertTrue(Pairing.CODE_PATTERN.matches(requested.code))
        assertTrue(pairing.poll() is PairingState.AwaitingApproval)
        assertTrue(fake.approve(requested.code))
        val shown = pairing.poll() as PairingState.ConfirmFingerprint
        assertEquals(Pairing.siteFingerprint(ca.certificatePem()), shown.fingerprint)
        assertEquals(fake.credentialId, shown.credentialId)
        assertNull("nothing is stored before the installer confirms", store.saved)

        val paired = pairing.answerFingerprint(matches = true) as PairingState.Paired
        val link = paired.link
        assertNull(SiteLink.validate(link))
        assertEquals(link, store.saved)
        assertEquals(listOf("save"), store.events)
        assertTrue(fake.confirmed)
        assertEquals(host, link.tlsHost)
        assertEquals(8443, link.port)
        assertEquals(certPin(ca.certificate.encoded), link.caPin)
        assertEquals(fake.token, link.token)
        assertEquals("ceiling_north", link.source)
        assertEquals("2027-03-30T00:00:00Z", link.expiresAt)
        assertEquals("Rosy Lab", link.siteName)
        assertTrue(link.secure)
        assertNull(link.manualHost)
    }

    @Test
    fun onlyDigestsLeaveThePhoneBeforeReveal() {
        val fake = FakeSite()
        client(fake).start(site)
        val request = JSONObject(fake.sent[0])
        val nonce = JSONObject(fake.sent[1]).getString("client_nonce")
        assertEquals(Pairing.commit(nonce), request.getString("client_commit"))
        assertFalse(fake.sent[0].contains(nonce))
    }

    @Test
    fun noStateCarriesASecret() {
        val fake = FakeSite()
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        assertFalse(pairing.state.toString().contains(fake.token))
        val paired = pairing.answerFingerprint(true)
        assertFalse(paired.toString().contains(fake.token))
    }

    @Test
    fun aRelayedLeafGivesADifferentCodeSoTheOperatorCannotApprove() {
        val relayCa = HeldCertificate.Builder().certificateAuthority(0).build()
        val relayLeaf = HeldCertificate.Builder().signedBy(relayCa).addSubjectAlternativeName(host).build()
        val fake = FakeSite(servedLeaf = relayLeaf.certificate)
        val requested = client(fake).start(site) as PairingState.Requested
        assertNotEquals(fake.code, requested.code)
        assertFalse(fake.approve(requested.code))
    }

    @Test
    fun aResultWhoseCaDidNotSignTheSeenLeafIsRejected() {
        // A fake receiver approving its own request (D-341 3 last point) still fails D-341 9 (a).
        val otherCa = HeldCertificate.Builder().certificateAuthority(0).build()
        val fake = FakeSite(caPem = otherCa.certificatePem())
        val pairing = client(fake)
        val requested = pairing.start(site) as PairingState.Requested
        fake.approve(requested.code)
        assertEquals(PairingState.Rejected("leaf_not_signed_by_ca"), pairing.poll())
        assertNull(store.saved)
    }

    @Test
    fun aLeafWithoutTheAdvertisedNameStopsBeforeAnyRequest() {
        val other = HeldCertificate.Builder().signedBy(ca).addSubjectAlternativeName("other.local").build()
        val fake = FakeSite(servedLeaf = other.certificate)
        assertEquals(PairingState.Rejected("leaf_san"), client(fake).start(site))
        assertTrue(fake.sent.isEmpty())
    }

    @Test
    fun aLeafAsSiteCaIsRejectedByTheResultRules() {
        val fake = FakeSite(caPem = leaf.certificatePem())
        val pairing = client(fake)
        fake.approve((pairing.start(site) as PairingState.Requested).code)
        assertEquals(PairingState.Rejected("leaf_not_ca"), pairing.poll())
    }

    @Test
    fun fingerprintMismatchStoresNothingAndDoesNotConfirm() {
        val fake = FakeSite()
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        assertEquals(PairingState.Rejected("fingerprint_mismatch"), pairing.answerFingerprint(matches = false))
        assertNull(store.saved)
        assertFalse(fake.confirmed)
    }

    @Test
    fun aRefusedConfirmDiscardsTheSavedLink() {
        val fake = FakeSite()
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        fake.refuseNext = PairingRefused(409, "CREDENTIAL_MISMATCH")
        assertEquals(PairingState.Rejected("credential_mismatch"), pairing.answerFingerprint(true))
        assertEquals(listOf("save", "discard"), store.events)
        assertNull(store.saved)
    }

    @Test
    fun aConfirmAfterTheDeadlineIsExpired() {
        val fake = FakeSite()
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        clock = clock.plusSeconds(PairingClient.CONFIRM_WITHIN_S)
        assertEquals(PairingState.Expired("confirm_deadline"), pairing.answerFingerprint(true))
        assertNull(store.saved)
    }

    @Test
    fun closedAndRefusedPolls() {
        fun started(): Pair<FakeSite, PairingClient> = FakeSite().let { it to client(it).also { c -> c.start(site) } }

        started().let { (fake, pairing) ->
            fake.state = "rejected"
            assertEquals(PairingState.Rejected("rejected"), pairing.poll())
        }
        started().let { (fake, pairing) ->
            fake.state = "expired"
            assertEquals(PairingState.Expired("expired"), pairing.poll())
        }
        started().let { (fake, pairing) ->
            fake.refuseNext = PairingRefused(404, "UNKNOWN_PAIRING_REQUEST")
            assertEquals(PairingState.Expired("unknown_request"), pairing.poll())
        }
        started().let { (fake, pairing) ->
            val before = pairing.state
            fake.refuseNext = PairingRefused(429, "POLL_TOO_FAST", retryAfterS = 2)
            assertEquals(before, pairing.poll())
            assertEquals(2L, pairing.retryAfterS)
            assertTrue(pairing.poll() is PairingState.AwaitingApproval)
            assertNull(pairing.retryAfterS)
        }
        started().let { (_, pairing) ->
            clock = clock.plusSeconds(301)
            assertEquals(PairingState.Expired("timeout"), pairing.poll())
            clock = Instant.parse("2026-10-01T00:00:00Z")
        }
    }

    @Test
    fun refusalsWhileStarting() {
        val busy = FakeSite().apply { refuseNext = PairingRefused(429, "PAIRING_PENDING_FULL", 10) }
        assertEquals(PairingState.Rejected("busy"), client(busy).start(site))
        val invalid = FakeSite().apply { refuseNext = PairingRefused(400, "PAIRING_REQUEST_INVALID") }
        assertEquals(PairingState.Rejected("pairing_request_invalid"), client(invalid).start(site))
    }

    @Test
    fun aFinishedClientCanStartAgain() {
        val fake = FakeSite()
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        pairing.answerFingerprint(false)
        assertTrue(pairing.start(site) is PairingState.Requested)
        pairing.cancel()
        assertEquals(PairingState.Discover, pairing.state)
    }
}
