package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.Vectors
import io.github.livsbittt.rosy.cam.settings.PairingUri
import java.net.InetAddress
import java.security.cert.CertificateException
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLPeerUnverifiedException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** Pinned site trust (D-341 9) against a throwaway site CA served by MockWebServer over TLS. */
class PinnedTrustTest {
    private val siteCa = HeldCertificate.Builder().commonName("rosy test site CA").certificateAuthority(0).build()
    private val otherCa = HeldCertificate.Builder().commonName("someone else").certificateAuthority(0).build()

    /** The site leaf carries an IP SAN only, like a site reached by address when .local does not resolve. */
    private fun leaf(issuer: HeldCertificate, san: String = LOOPBACK) =
        HeldCertificate.Builder().commonName("site").addSubjectAlternativeName(san).signedBy(issuer).build()

    private val servers = mutableListOf<MockWebServer>()
    private var link: OverheadLink? = null

    @After
    fun tearDown() {
        link?.stop()
        servers.forEach { it.shutdown() }
    }

    private fun serve(leaf: HeldCertificate, vararg intermediates: HeldCertificate): MockWebServer {
        val certs = HandshakeCertificates.Builder()
            .heldCertificate(leaf, *intermediates.map { it.certificate }.toTypedArray())
            .build()
        return MockWebServer().also {
            it.useHttps(certs.sslSocketFactory(), false)
            it.start(InetAddress.getByName(LOOPBACK), 0)
            servers += it
        }
    }

    private fun get(client: OkHttpClient, server: MockWebServer): Int {
        server.enqueue(MockResponse().setBody("ok"))
        client.newCall(Request.Builder().url("https://$LOOPBACK:${server.port}/").build()).execute().use { return it.code }
    }

    private fun failure(client: OkHttpClient, server: MockWebServer): Throwable {
        try {
            get(client, server)
        } catch (e: Exception) {
            return e
        }
        fail("expected the TLS handshake to fail")
        throw AssertionError()
    }

    @Test
    fun certPinMatchesTheSharedVector() {
        val vectors = Vectors.root.getJSONObject("cert_pins").getJSONArray("vectors")
        assertTrue(vectors.length() > 0)
        for (i in 0 until vectors.length()) {
            val v = vectors.getJSONObject(i)
            assertEquals(v.getString("pin"), certPin(v.getString("der_utf8").toByteArray(Charsets.UTF_8)))
            assertTrue(PairingUri.PIN_PATTERN.matches(v.getString("pin")))
        }
    }

    @Test
    fun caPinAcceptsALeafTheCaSigned() {
        // The `rosy-vision pair-link --pin-ca` path: the proxy serves leaf + CA (site-fullchain.crt), the link pins the CA.
        val server = serve(leaf(siteCa), siteCa)
        assertEquals(200, get(OverheadLink.defaultClient(certPin(siteCa.certificate.encoded)), server))
    }

    @Test
    fun leafPinAcceptsALeafOnlyServer() {
        val siteLeaf = leaf(siteCa)
        val server = serve(siteLeaf)
        assertEquals(200, get(OverheadLink.defaultClient(certPin(siteLeaf.certificate.encoded)), server))
    }

    @Test
    fun caPinRejectsAChainFromAnotherCa() {
        val server = serve(leaf(otherCa), otherCa)
        val error = failure(OverheadLink.defaultClient(certPin(siteCa.certificate.encoded)), server)
        assertEquals(NetworkFailure.TLS_PIN, NetworkFailure.classify(error))
    }

    @Test
    fun caPinRejectsAForgedLeafThatOnlyAppendsTheRealCa() {
        // An attacker can send the public site CA certificate, but cannot make it sign their leaf.
        // The JDK refuses to serve such a broken chain, so the trust manager is driven directly.
        val forged = arrayOf(leaf(otherCa).certificate, siteCa.certificate)
        val trust = PinnedTrustManager(certPin(siteCa.certificate.encoded))
        try {
            trust.checkServerTrusted(forged, "ECDHE_ECDSA")
            fail("a leaf the pinned CA did not sign must be rejected")
        } catch (e: CertificateException) {
            assertTrue(e.toString(), e !is PinMismatchException)
        }
        trust.checkServerTrusted(arrayOf(leaf(siteCa).certificate, siteCa.certificate), "ECDHE_ECDSA")
    }

    @Test
    fun caPinStillRequiresTheHostnameInTheCertificate() {
        val server = serve(leaf(siteCa, san = "192.0.2.99"), siteCa)
        val error = failure(OverheadLink.defaultClient(certPin(siteCa.certificate.encoded)), server)
        assertTrue(error.toString(), error is SSLPeerUnverifiedException)
        assertEquals(NetworkFailure.TLS, NetworkFailure.classify(error))
    }

    @Test
    fun leafPinStillRequiresTheHostnameInTheCertificate() {
        val wrongName = leaf(siteCa, san = "192.0.2.99")
        val server = serve(wrongName, siteCa)
        val error = failure(OverheadLink.defaultClient(certPin(wrongName.certificate.encoded)), server)
        assertTrue(error.toString(), error is SSLPeerUnverifiedException)
        assertEquals(NetworkFailure.TLS, NetworkFailure.classify(error))
    }

    @Test
    fun leafPinRejectsAnotherLeafFromTheSameCa() {
        val pinned = leaf(siteCa)
        val server = serve(leaf(siteCa), siteCa)
        val error = failure(OverheadLink.defaultClient(certPin(pinned.certificate.encoded)), server)
        assertEquals(NetworkFailure.TLS_PIN, NetworkFailure.classify(error))
    }

    @Test
    fun leafPinAboveAnotherLeafIsRejected() {
        val pinned = leaf(siteCa)
        val attacker = leaf(otherCa)
        val trust = PinnedTrustManager(certPin(pinned.certificate.encoded))
        assertRejected(trust, arrayOf(attacker.certificate, pinned.certificate))
    }

    @Test
    fun expiredCertificatesAreRejectedUnderLeafAndCaPins() {
        val now = System.currentTimeMillis()
        val day = TimeUnit.DAYS.toMillis(1)
        val expiredLeaf = HeldCertificate.Builder().commonName("site").addSubjectAlternativeName(LOOPBACK)
            .validityInterval(now - 2 * day, now - day).signedBy(siteCa).build()
        assertRejected(PinnedTrustManager(certPin(expiredLeaf.certificate.encoded)), arrayOf(expiredLeaf.certificate))
        assertRejected(
            PinnedTrustManager(certPin(siteCa.certificate.encoded)),
            arrayOf(expiredLeaf.certificate, siteCa.certificate),
        )
        // PKIX skips the anchor's own dates, so an expired pinned CA is checked explicitly.
        val expiredCa = HeldCertificate.Builder().commonName("old site CA").certificateAuthority(0)
            .validityInterval(now - 2 * day, now - day).build()
        assertRejected(
            PinnedTrustManager(certPin(expiredCa.certificate.encoded)),
            arrayOf(leaf(expiredCa).certificate, expiredCa.certificate),
        )
    }

    @Test
    fun aPeerReasonPhraseCannotForceAPinStopOnPlainWs() {
        val plain = MockWebServer().also { it.start(InetAddress.getByName(LOOPBACK), 0); servers += it }
        repeat(3) { plain.enqueue(MockResponse().setStatus("HTTP/1.1 503 ${PinMismatchException.MARKER}: fake")) }
        val l = OverheadLink(PairingUri(LOOPBACK, plain.port, "secret-token", "overhead-1"), "0.1.0", "jvm-test")
            .also { link = it }
        l.start()
        val status = awaitStatus(l) { it.error != null }
        assertTrue(status.toString(), !status.stopped)
        val error = status.error as LinkError.Network
        assertTrue(error.toString(), error.kind != NetworkFailure.TLS_PIN)
    }

    private fun assertRejected(trust: PinnedTrustManager, chain: Array<java.security.cert.X509Certificate>) {
        try {
            trust.checkServerTrusted(chain, "ECDHE_ECDSA")
            fail("chain must be rejected")
        } catch (e: CertificateException) {
            assertTrue(e.toString(), e !is PinMismatchException)
        }
    }

    @Test
    fun noPinKeepsTheSystemTrustStoreAndRejectsTheSiteCa() {
        val server = serve(leaf(siteCa), siteCa)
        val error = failure(OverheadLink.defaultClient(null), server)
        assertEquals(NetworkFailure.TLS, NetworkFailure.classify(error))
    }

    @Test
    fun pinnedWssLinkStreamsAndAMismatchStopsTheLink() {
        val server = serve(leaf(siteCa), siteCa)
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, null)
            }
        }))
        val pinned = PairingUri(LOOPBACK, server.port, "secret-token", "overhead-1", secure = true, pin = certPin(siteCa.certificate.encoded))
        val good = OverheadLink(pinned, "0.1.0", "jvm-test").also { link = it }
        good.start()
        awaitStatus(good) { it.state == LinkState.STREAMING }
        assertEquals("Bearer secret-token", server.takeRequest(5, TimeUnit.SECONDS)!!.getHeader("Authorization"))
        good.stop()

        val wrong = pinned.copy(pin = certPin(otherCa.certificate.encoded))
        val bad = OverheadLink(wrong, "0.1.0", "jvm-test").also { link = it }
        bad.start()
        val status = awaitStatus(bad) { it.stopped }
        val error = status.error as LinkError.Network
        assertEquals(NetworkFailure.TLS_PIN, error.kind)
    }

    private fun awaitStatus(l: OverheadLink, predicate: (LinkStatus) -> Boolean): LinkStatus = runBlocking {
        withTimeout(10_000) { l.status.first(predicate) }
    }

    private companion object {
        const val LOOPBACK = "127.0.0.1"
    }
}
