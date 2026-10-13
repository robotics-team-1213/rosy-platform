package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.net.InetAddress
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import javax.net.ssl.SNIHostName
import javax.net.ssl.SNIMatcher
import javax.net.ssl.SNIServerName
import javax.net.ssl.SSLPeerUnverifiedException
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.StandardConstants
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * The URL keeps `tls_host` while TCP goes to the address mDNS found (D-391 1): SNI and hostname verification
 * check `tls_host` against the pinned site CA. MockWebServer on 127.0.0.1 stands in for the site; a fake NSD
 * maps `rosy-site.local` to it. The certificate carries no IP SAN, so only the name can pass.
 */
class SiteDnsTlsTest {
    private val siteCa = HeldCertificate.Builder().commonName("rosy test site CA").certificateAuthority(0).build()
    private val caPin = certPin(siteCa.certificate.encoded)
    private val servers = mutableListOf<MockWebServer>()

    @After
    fun tearDown() {
        servers.forEach { it.shutdown() }
    }

    /** SNI host names the server saw, recorded by an accept-all SNI matcher. */
    private val sniSeen = CopyOnWriteArrayList<String>()

    /** Server socket factory that records the client's SNI before the handshake. */
    private inner class SniRecording(private val delegate: SSLSocketFactory) : SSLSocketFactory() {
        private fun record(socket: Socket): Socket = socket.also { s ->
            val ssl = s as SSLSocket
            ssl.sslParameters = ssl.sslParameters.apply {
                sniMatchers = listOf(object : SNIMatcher(StandardConstants.SNI_HOST_NAME) {
                    override fun matches(serverName: SNIServerName): Boolean {
                        sniSeen += (serverName as? SNIHostName)?.asciiName ?: String(serverName.encoded)
                        return true
                    }
                })
            }
        }

        override fun getDefaultCipherSuites(): Array<String> = delegate.defaultCipherSuites
        override fun getSupportedCipherSuites(): Array<String> = delegate.supportedCipherSuites
        override fun createSocket(s: Socket, host: String?, port: Int, autoClose: Boolean): Socket =
            record(delegate.createSocket(s, host, port, autoClose))
        override fun createSocket(host: String, port: Int): Socket = record(delegate.createSocket(host, port))
        override fun createSocket(host: String, port: Int, localHost: InetAddress, localPort: Int): Socket =
            record(delegate.createSocket(host, port, localHost, localPort))
        override fun createSocket(host: InetAddress, port: Int): Socket = record(delegate.createSocket(host, port))
        override fun createSocket(address: InetAddress, port: Int, localAddress: InetAddress, localPort: Int): Socket =
            record(delegate.createSocket(address, port, localAddress, localPort))
    }

    private fun serve(san: String): MockWebServer {
        val leaf = HeldCertificate.Builder().commonName("site").addSubjectAlternativeName(san).signedBy(siteCa).build()
        val certs = HandshakeCertificates.Builder().heldCertificate(leaf, siteCa.certificate).build()
        return MockWebServer().also {
            it.useHttps(SniRecording(certs.sslSocketFactory()), false)
            it.start(InetAddress.getByName(LOOPBACK), 0)
            servers += it
        }
    }

    private fun link(port: Int, manualHost: String? = null) =
        SiteLink("Rosy site", TLS_HOST, port, caPin, "t", "overhead-1", secure = true, manualHost = manualHost)

    /** Fake NSD: the site advertised at [addresses], or nothing on this network when none are given. */
    private fun browser(vararg addresses: String) = SiteBrowser { _, match ->
        if (addresses.isEmpty()) emptyList()
        else listOf(SiteSighting("Rosy site", TLS_HOST, 443, addresses.map { InetAddress.getByName(it) })).filter(match)
    }

    private fun client(link: SiteLink, browser: SiteBrowser): OkHttpClient =
        OverheadLink.defaultClient(link.caPin, SiteDns(TLS_HOST, SiteResolver(link, browser)))

    private fun get(client: OkHttpClient, server: MockWebServer): Int {
        server.enqueue(MockResponse().setBody("ok"))
        client.newCall(Request.Builder().url("https://$TLS_HOST:${server.port}/").build()).execute().use { return it.code }
    }

    @Test
    fun mdnsAddressWithTlsHostAsSniAndHostname() {
        val server = serve(TLS_HOST)
        val link = link(server.port)
        assertEquals(200, get(client(link, browser(LOOPBACK)), server))
        assertEquals(listOf(TLS_HOST), sniSeen)
    }

    @Test
    fun aCertificateForAnotherNameIsRejectedEvenFromThePinnedCa() {
        val server = serve("other-site.local")
        try {
            get(client(link(server.port), browser(LOOPBACK)), server)
            fail("expected hostname verification to fail")
        } catch (e: SSLPeerUnverifiedException) {
            assertEquals(NetworkFailure.TLS, NetworkFailure.classify(e))
        }
    }

    @Test
    fun manualFallbackStillVerifiesTlsHost() {
        // mDNS finds nothing; the manual IP carries TCP, and the certificate is still checked for tls_host.
        val server = serve(TLS_HOST)
        val link = link(server.port, manualHost = LOOPBACK)
        assertEquals(200, get(client(link, browser()), server))
    }

    @Test
    fun aLearnedNameMustBeInTheLeafOfALivePinnedHandshake() {
        // Review M2: an IP-only link learns tls_host only when the pinned site's own leaf names it.
        val leaf = HeldCertificate.Builder().commonName("site")
            .addSubjectAlternativeName(LOOPBACK).addSubjectAlternativeName(TLS_HOST).signedBy(siteCa).build()
        val certs = HandshakeCertificates.Builder().heldCertificate(leaf, siteCa.certificate).build()
        val server = MockWebServer().also {
            it.useHttps(certs.sslSocketFactory(), false)
            it.start(InetAddress.getByName(LOOPBACK), 0)
            servers += it
        }
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onClosing(webSocket: okhttp3.WebSocket, code: Int, reason: String) {
                webSocket.close(code, null)
            }
        }))
        val pairing = SiteLink(null, null, server.port, caPin, "t", "overhead-1", secure = true, manualHost = LOOPBACK).toPairing()
        val link = OverheadLink(pairing, "0.1.0", "jvm-test")
        try {
            link.start()
            val status = runBlocking {
                withTimeout(10_000) { link.status.first { it.state == LinkState.STREAMING || it.error != null } }
            }
            assertEquals(status.toString(), LinkState.STREAMING, status.state)
            val peer = runBlocking { withTimeout(10_000) { link.peerLeaf.filterNotNull().first() } }
            assertTrue(SiteResolver.leafCovers(TLS_HOST, peer))
            assertFalse(SiteResolver.leafCovers("evil.local", peer))
        } finally {
            link.stop()
        }
        assertFalse(SiteResolver.leafCovers(TLS_HOST, null))
    }

    @Test
    fun aPinMismatchOnADiscoveredAddressBrowsesAgainBeforeStopping() {
        // Review M3: one spoofed advert must not stop the camera for good. The impostor serves a chain from
        // another CA at the advertised address, every time.
        val otherCa = HeldCertificate.Builder().commonName("impostor CA").certificateAuthority(0).build()
        val impostorLeaf = HeldCertificate.Builder().commonName("x").addSubjectAlternativeName(TLS_HOST).signedBy(otherCa).build()
        val certs = HandshakeCertificates.Builder().heldCertificate(impostorLeaf, otherCa.certificate).build()
        val server = MockWebServer().also {
            it.useHttps(certs.sslSocketFactory(), false)
            it.start(InetAddress.getByName(LOOPBACK), 0)
            servers += it
        }
        var browses = 0
        val spoofed = SiteBrowser { _, match ->
            browses++
            listOf(SiteSighting("Rosy site", TLS_HOST, 443, listOf(InetAddress.getByName(LOOPBACK)))).filter(match)
        }
        val site = link(server.port)
        val link = OverheadLink(site.toPairing(), "0.1.0", "jvm-test", SiteResolver(site, spoofed))
        try {
            link.start()
            val first = runBlocking { withTimeout(10_000) { link.status.first { it.error != null } } }
            assertEquals(NetworkFailure.TLS_PIN, (first.error as LinkError.Network).kind)
            assertFalse("first pin mismatch via discovery must retry", first.stopped)
            val last = runBlocking { withTimeout(10_000) { link.status.first { it.stopped } } }
            assertEquals(NetworkFailure.TLS_PIN, (last.error as LinkError.Network).kind)
            assertEquals("the retry must come from a fresh browse", 2, browses)
        } finally {
            link.stop()
        }
    }

    @Test
    fun notDiscoveredFailsBeforeAnySocket() {
        val server = serve(TLS_HOST)
        try {
            get(client(link(server.port), browser()), server)
            fail("expected not_discovered")
        } catch (e: Exception) {
            assertEquals(NetworkFailure.NOT_DISCOVERED, NetworkFailure.classify(e))
        }
        assertEquals(0, server.requestCount)
    }

    private companion object {
        const val LOOPBACK = "127.0.0.1"
        const val TLS_HOST = "rosy-site.local"
    }
}
