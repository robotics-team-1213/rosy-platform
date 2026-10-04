package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.link.certPin
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.nio.charset.StandardCharsets.UTF_8
import java.security.cert.X509Certificate
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
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
        val resultTlsHost: String = host,
        val siteName: String = "Rosy Lab",
        val expiresAt: String = "2026-10-01T00:05:00Z",
    ) : PairingTransport {
        /** The first [lostReplies] confirm calls activate the credential but lose the reply (I/O failure). */
        var lostReplies = 0

        /** Thrown by every confirm call after the first (the single resend). */
        var retryRefusal: PairingRefused? = null
        var pollThrows: RuntimeException? = null
        var confirmCalls = 0
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
                .put("expires_at", expiresAt).toString().toByteArray(UTF_8)
        }

        override fun reveal(site: PairableSite, requestId: String, pollKey: String, body: ByteArray): ByteArray {
            sent += String(body, UTF_8)
            refuse()
            assertEquals(pollDigest, Pairing.sha256Text(pollKey))
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
            .put("site_name", siteName).put("source_id", "ceiling_north").put("tls_host", resultTlsHost)
            .put("site_ca_pem", caPem).put("token", token).put("credential_id", credentialId)
            .put("expires_at", "2027-03-30T00:00:00Z")

        override fun poll(site: PairableSite, requestId: String, pollKey: String): ByteArray {
            refuse()
            pollThrows?.let { throw it }
            if (Pairing.sha256Text(pollKey) != pollDigest) throw PairingRefused(401, "POLL_SECRET_INVALID")
            if (state == "delivered") throw PairingRefused(410, "PAIRING_RESULT_GONE")
            if (state != "approved") return JSONObject().put("state", state).toString().toByteArray(UTF_8)
            state = "delivered"
            return JSONObject().put("state", "approved").put("result", result()).toString().toByteArray(UTF_8)
        }

        override fun confirm(site: PairableSite, requestId: String, pollKey: String, body: ByteArray): ByteArray {
            confirmCalls++
            refuse()
            if (confirmCalls > 1) retryRefusal?.let { throw it }
            val id = JSONObject(String(body, UTF_8)).getString("credential_id")
            // rosy-00 d5d4a2e4: a repeat confirm of the same credential answers the same 200.
            val repeat = state == "confirmed" && id == credentialId
            if (!repeat && state != "delivered") throw PairingRefused(409, "NOT_DELIVERED")
            if (id != credentialId) throw PairingRefused(409, "CREDENTIAL_MISMATCH")
            confirmed = true
            state = "confirmed"
            if (confirmCalls <= lostReplies) throw java.io.IOException("connection reset after the server activated the credential")
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

    /** Waits the client asked for before resending confirm; the clock moves by [pauseAdvanceS] each time. */
    private val pauses = mutableListOf<Long>()
    private var pauseAdvanceS = 1L

    private fun client(fake: FakeSite) =
        PairingClient(fake, "Galaxy S21 ceiling", "0.4.0", store, now = { clock }, pause = { ms ->
            pauses += ms
            clock = clock.plusSeconds(pauseAdvanceS)
        })

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
        // D-341 9 (a): the delivered CA did not sign the leaf seen on first contact (e.g. a relay passing on another
        // site's result). A self-approving receiver with its own CA passes this check; see the rogue test below.
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
        assertEquals(PairingState.Rejected("confirm_credential_mismatch", fake.credentialId), pairing.answerFingerprint(true))
        assertEquals(listOf("save", "discard"), store.events)
        assertNull(store.saved)
        assertEquals("a refused confirm is never resent", 1, fake.confirmCalls)
        assertTrue(pauses.isEmpty())
    }

    @Test
    fun unansweredConfirmIsResentOnce_match200KeepsLink() {
        val fake = FakeSite().apply { lostReplies = 1 }
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        val paired = pairing.answerFingerprint(true) as PairingState.Paired
        assertEquals(paired.link, store.saved)
        assertEquals("saved once, never discarded", listOf("save"), store.events)
        assertEquals(2, fake.confirmCalls)
        assertEquals(listOf(PairingClient.CONFIRM_RETRY_MS), pauses)
    }

    @Test
    fun aConfirmWithoutAnswerTwiceDiscardsTheLinkAndNamesTheCredential() {
        // The server activated it, both replies were lost: the phone keeps nothing and asks for a revoke (review M6).
        val fake = FakeSite().apply { lostReplies = 2 }
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        val final = pairing.answerFingerprint(true)
        assertEquals(PairingState.Rejected(PairingClient.CONFIRM_UNANSWERED, fake.credentialId), final)
        assertEquals(listOf("save", "discard"), store.events)
        assertNull(store.saved)
        assertTrue("the server side is active", fake.confirmed)
        assertEquals(final, pairing.state)
        assertEquals("exactly one resend", 2, fake.confirmCalls)
    }

    @Test
    fun anUnansweredConfirmWhoseResendIsRefusedDiscardsTheLink() {
        val fake = FakeSite().apply {
            lostReplies = 1
            retryRefusal = PairingRefused(410, "PAIRING_REQUEST_CLOSED") // revoked meanwhile
        }
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        assertEquals(PairingState.Rejected(PairingClient.CONFIRM_UNANSWERED, fake.credentialId), pairing.answerFingerprint(true))
        assertEquals(listOf("save", "discard"), store.events)
        assertEquals(2, fake.confirmCalls)
    }

    @Test
    fun noResendOnceTheConfirmWindowHasClosed() {
        val fake = FakeSite().apply { lostReplies = 1 }
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        pauseAdvanceS = PairingClient.CONFIRM_WITHIN_S
        assertEquals(PairingState.Rejected(PairingClient.CONFIRM_UNANSWERED, fake.credentialId), pairing.answerFingerprint(true))
        assertEquals(1, fake.confirmCalls)
        assertEquals(listOf("save", "discard"), store.events)
    }

    @Test
    fun aConfirm410IsNotAPoll410() {
        val polled = FakeSite()
        val first = client(polled)
        first.start(site)
        polled.refuseNext = PairingRefused(410, "PAIRING_RESULT_GONE")
        assertEquals(PairingState.Expired("gone"), first.poll())

        val fake = FakeSite()
        val pairing = client(fake)
        toFingerprint(fake, pairing)
        fake.refuseNext = PairingRefused(410, "PAIRING_REQUEST_CLOSED")
        assertEquals(PairingState.Expired("confirm_gone", fake.credentialId), pairing.answerFingerprint(true))
        assertEquals(listOf("save", "discard"), store.events)
    }

    @Test
    fun aResultTlsHostTheLeafDoesNotNameIsRejected() {
        // D-341 9 (b): the CA signs the seen leaf, but the leaf does not name the delivered tls_host (review M3).
        val fake = FakeSite(resultTlsHost = "other.local")
        val pairing = client(fake)
        fake.approve((pairing.start(site) as PairingState.Requested).code)
        assertEquals(PairingState.Rejected("leaf_san"), pairing.poll())
        assertNull(store.saved)
        assertFalse(fake.confirmed)
    }

    @Test
    fun aRogueSelfApprovingReceiverOnlyGetsAsFarAsADifferentFingerprint() {
        // A fake _rosy-overhead._tcp receiver with its own CA approves its own request: code and D-341 9 both pass,
        // so only the installer's fingerprint comparison (D-341 4) stops it. Nothing is stored before "match".
        val rogueCa = HeldCertificate.Builder().certificateAuthority(0).commonName("Rosy test site CA").build()
        val rogueLeaf = HeldCertificate.Builder().signedBy(rogueCa).addSubjectAlternativeName(host).build()
        val rogue = FakeSite(servedLeaf = rogueLeaf.certificate, serverLeaf = rogueLeaf.certificate, caPem = rogueCa.certificatePem())
        val pairing = client(rogue)
        assertTrue(rogue.approve((pairing.start(site) as PairingState.Requested).code))
        val shown = pairing.poll() as PairingState.ConfirmFingerprint
        assertNotEquals(Pairing.siteFingerprint(ca.certificatePem()), shown.fingerprint)
        assertNull(store.saved)
        assertEquals(PairingState.Rejected("fingerprint_mismatch"), pairing.answerFingerprint(false))
        assertNull(store.saved)
        assertTrue(store.events.isEmpty())
        assertFalse(rogue.confirmed)
    }

    @Test
    fun onlyPlainS2CodesBecomeReasons() {
        for ((code, want) in listOf("PAIRING_REQUEST_INVALID" to "pairing_request_invalid", "<b>bad</b>" to "refused_400",
            "commit_mismatch" to "refused_400", "A".repeat(41) to "refused_400", null to "refused_400")) {
            val fake = FakeSite().apply { refuseNext = PairingRefused(400, code) }
            assertEquals("$code", PairingState.Rejected(want), client(fake).start(site))
        }
    }

    @Test
    fun theSiteNameIsCappedBeforeItIsShownOrStored() {
        val fake = FakeSite(siteName = "‮" + "Rosy\u0007 Lab " + "x".repeat(100))
        val pairing = client(fake)
        val shown = toFingerprint(fake, pairing)
        val stored = (pairing.answerFingerprint(true) as PairingState.Paired).link.siteName!!
        for (name in listOf(shown.siteName, stored)) {
            assertTrue(name, name.codePointCount(0, name.length) <= PairingClient.SITE_NAME_LIMIT)
            assertTrue(name, name.startsWith("Rosy Lab"))
            assertFalse(name, name.any { Character.getType(it) == Character.CONTROL.toInt() || Character.getType(it) == Character.FORMAT.toInt() })
        }
        assertEquals("tls_host stands in for a name with nothing printable", host, Pairing.capText("​\u0001", 64).ifEmpty { host })
    }

    /** A session whose first sleep approves the request, so it stops at the fingerprint step. */
    private fun CoroutineScope.sessionAtFingerprint(fake: FakeSite): PairingSession {
        val pairing = client(fake)
        return PairingSession(pairing, this, Dispatchers.IO) { fake.code?.let(fake::approve) }
    }

    @Test
    fun busyIsSetBeforeTheStartIsLaunched() = runBlocking {
        val fake = FakeSite()
        val session = sessionAtFingerprint(fake)
        session.start(site)
        assertTrue("busy in the same frame as the tap", session.busy.value)
        session.start(site) // second tap: ignored
        session.join()
        assertTrue(session.state.value is PairingState.ConfirmFingerprint)
        assertEquals(1, fake.sent.count { it.contains("client_commit") })
    }

    @Test
    fun aDoubleTapOrACancelCannotInterruptTheAnswer() = runBlocking {
        val fake = FakeSite()
        val session = sessionAtFingerprint(fake)
        session.start(site)
        session.join()
        session.answer(true)
        session.answer(true)
        session.cancel()
        session.join()
        assertTrue(session.state.value is PairingState.Paired)
        assertEquals(1, fake.confirmCalls)
        assertEquals(listOf("save"), store.events)
    }

    @Test
    fun anUnexpectedExceptionEndsTheAttemptInsteadOfEscaping() = runBlocking {
        val fake = FakeSite().apply { pollThrows = IllegalStateException("bug") }
        val session = PairingSession(client(fake), this, Dispatchers.IO) { }
        session.start(site)
        session.join()
        assertEquals(PairingState.Rejected("internal"), session.state.value)
        assertFalse(session.busy.value)
    }

    @Test
    fun theWaitIsBoundedByOurOwnStartWhateverTheSiteClaims() {
        val fake = FakeSite(expiresAt = "2099-01-01T00:00:00Z")
        val pairing = client(fake)
        pairing.start(site)
        clock = clock.plusSeconds(PairingClient.MAX_PENDING_S - 1)
        assertTrue(pairing.poll() is PairingState.AwaitingApproval)
        clock = clock.plusSeconds(1)
        assertEquals(PairingState.Expired("timeout"), pairing.poll())
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
