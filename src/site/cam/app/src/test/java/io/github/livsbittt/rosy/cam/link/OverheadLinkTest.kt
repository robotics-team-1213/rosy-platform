package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.settings.PairingUri
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.ByteString
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Drives OverheadLink against an in-process WebSocket server on the JVM. */
class OverheadLinkTest {
    private lateinit var server: MockWebServer
    private var link: OverheadLink? = null

    /** Server side of one accepted connection. */
    private class ServerSide : WebSocketListener() {
        val texts = LinkedBlockingQueue<String>()
        val binaries = LinkedBlockingQueue<ByteString>()
        val opened = LinkedBlockingQueue<WebSocket>()

        override fun onOpen(webSocket: WebSocket, response: Response) {
            opened.add(webSocket)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            texts.add(text)
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            binaries.add(bytes)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code, null)
        }
    }

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        link?.stop()
        server.shutdown()
    }

    private fun newLink(): OverheadLink {
        val pairing = PairingUri(server.hostName, server.port, "secret-token", "overhead-1")
        return OverheadLink(pairing, appVersion = "0.1.0", device = "jvm-test").also {
            it.sensor = SensorInfo(1280, 720, 90)
            link = it
        }
    }

    private fun awaitStatus(l: OverheadLink, predicate: (LinkStatus) -> Boolean): LinkStatus = runBlocking {
        withTimeout(10_000) { l.status.first(predicate) }
    }

    @Test
    fun sendsBearerAndHelloThenFramesWithIncreasingSeq() {
        val side = ServerSide()
        server.enqueue(MockResponse().withWebSocketUpgrade(side))
        val l = newLink()
        l.start()

        val request = server.takeRequest(5, TimeUnit.SECONDS)
        assertNotNull(request)
        assertEquals("Bearer secret-token", request!!.getHeader("Authorization"))
        assertEquals(Protocol.WS_PATH, request.path)

        val hello = JSONObject(side.texts.poll(5, TimeUnit.SECONDS)!!)
        assertEquals("hello", hello.getString("type"))
        assertEquals(Protocol.PROTO, hello.getString("proto"))
        assertEquals("overhead-1", hello.getString("source"))
        assertEquals(90, hello.getJSONObject("sensor").getInt("rotation_deg"))

        awaitStatus(l) { it.state == LinkState.STREAMING }
        val jpeg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2, 3, 0xFF.toByte(), 0xD9.toByte())
        for (expectedSeq in 0L..1L) {
            awaitAdmitted(l)
            assertTrue(l.sendFrame(jpeg, jpeg.size, 1280, 720, 90, System.nanoTime()))
            val frame = side.binaries.poll(5, TimeUnit.SECONDS)!!.toByteArray()
            val parsed = FrameHeader.parse(frame) as FrameHeader.Parsed.Valid
            assertEquals(expectedSeq, parsed.header.seq)
            assertEquals(1280, parsed.header.width)
            assertEquals(90, parsed.header.rotationDeg)
            assertArrayEquals(jpeg, frame.copyOfRange(FrameHeader.SIZE, frame.size))
        }
    }

    @Test
    fun reconnectSendsAFreshHelloWithTheNewLensAtOnce() {
        val first = ServerSide()
        val second = ServerSide()
        server.enqueue(MockResponse().withWebSocketUpgrade(first))
        server.enqueue(MockResponse().withWebSocketUpgrade(second))
        val l = newLink()
        l.lens = HelloLens("standard", 5.4, 67.8)
        l.start()
        val hello1 = JSONObject(first.texts.poll(5, TimeUnit.SECONDS)!!)
        assertEquals("standard", hello1.getJSONObject("lens").getString("kind"))
        awaitStatus(l) { it.state == LinkState.STREAMING }

        l.lens = HelloLens("wide", 2.2, 104.1)
        val started = System.nanoTime()
        l.reconnect()
        val hello2 = JSONObject(second.texts.poll(5, TimeUnit.SECONDS)!!)
        // No backoff delay: a lens change is not a failure.
        assertTrue(System.nanoTime() - started < TimeUnit.MILLISECONDS.toNanos(900))
        assertEquals("wide", hello2.getJSONObject("lens").getString("kind"))
        assertEquals(2.2, hello2.getJSONObject("lens").getDouble("focal_mm"), 0.0)
        val status = awaitStatus(l) { it.state == LinkState.STREAMING }
        assertEquals(null, status.error)
    }

    @Test
    fun appliesConfigAndDropsFramesAboveMaxBytes() {
        val side = ServerSide()
        server.enqueue(MockResponse().withWebSocketUpgrade(side))
        val l = newLink()
        l.start()
        val serverSocket = side.opened.poll(5, TimeUnit.SECONDS)!!
        awaitStatus(l) { it.state == LinkState.STREAMING }

        serverSocket.send("""{"type":"config","fps":2,"width":960,"jpeg_quality":60,"max_bytes":10}""")
        val status = awaitStatus(l) { it.config.maxBytes == 10 }
        assertEquals(OverheadConfig(2.0, 960, 60, 10), status.config)

        assertFalse(l.sendFrame(ByteArray(11), 11, 960, 540, 0, System.nanoTime()))
        awaitStatus(l) { it.dropped == 1L }
    }

    @Test
    fun publishesAdapterStatusAndClearsItWhenTheLinkDrops() {
        val side = ServerSide()
        server.enqueue(MockResponse().withWebSocketUpgrade(side))
        server.enqueue(MockResponse().setResponseCode(503))
        val l = newLink()
        l.start()
        val serverSocket = side.opened.poll(5, TimeUnit.SECONDS)!!
        awaitStatus(l) { it.state == LinkState.STREAMING }

        serverSocket.send("""{"type":"status","corners_seen":[30,31],"corners_needed":4,"robots_seen":["rosy_01"],"rx_fps":3.0,"dropped":0}""")
        val withSite = awaitStatus(l) { it.site != null }
        assertEquals(listOf(30, 31), withSite.site!!.cornersSeen)

        serverSocket.close(1011, "restart")
        val dropped = awaitStatus(l) { it.state == LinkState.DISCONNECTED }
        assertEquals("stale marker counts must not outlive the connection", null, dropped.site)
    }

    @Test
    fun connectFailureCarriesItsKind() {
        val port = server.port
        server.shutdown()
        val pairing = PairingUri("127.0.0.1", port, "secret-token", "overhead-1")
        val l = OverheadLink(pairing, appVersion = "0.1.0", device = "jvm-test").also { link = it }
        l.start()
        val failed = awaitStatus(l) { it.error is LinkError.Network }
        assertEquals(NetworkFailure.REFUSED, (failed.error as LinkError.Network).kind)
        server = MockWebServer().also { it.start() }
    }

    @Test
    fun connectFailureForcesAFreshBrowse() {
        // Tablet 2026-10-01: Android's NSD cache can keep a dead advertiser resolvable for minutes; the app's
        // own 30 s cache must still be dropped by a failed connect so the next attempt browses again.
        val port = server.port
        server.shutdown()
        var browses = 0
        val browser = SiteBrowser { _, match ->
            browses++
            listOf(SiteSighting("Rosy site", "rosy-site.local", port, listOf(java.net.InetAddress.getByName("127.0.0.1")))).filter(match)
        }
        val site = io.github.livsbittt.rosy.cam.settings.SiteLink(null, "rosy-site.local", port, null, "t", "overhead-1", secure = false)
        val resolver = SiteResolver(site, browser)
        val l = OverheadLink(site.toPairing(), appVersion = "0.1.0", device = "jvm-test", resolver = resolver).also { link = it }
        l.start()
        awaitStatus(l) { it.error is LinkError.Network }
        l.stop()
        val afterFailure = browses
        resolver.resolve()
        assertEquals("a failed connect must drop the cached address", afterFailure + 1, browses)
        server = MockWebServer().also { it.start() }
    }

    @Test
    fun protocolMismatchCloseStopsRetrying() {
        val side = ServerSide()
        server.enqueue(MockResponse().withWebSocketUpgrade(side))
        val l = newLink()
        l.start()
        side.opened.poll(5, TimeUnit.SECONDS)!!.close(Protocol.CLOSE_BAD_PROTO, "proto")

        val status = awaitStatus(l) { it.stopped }
        assertEquals(LinkError.ProtocolMismatch, status.error)
        assertEquals(LinkState.DISCONNECTED, status.state)
        assertNoReconnect("4400")
        assertFalse(l.admitFrame())
    }

    @Test
    fun noHelloTimeoutAndTryAgainLaterRetryInsteadOfStopping() {
        // 2026-10-01 device test: Vision's loop was blocked, its hello timer closed with 4400 "no hello".
        for ((code, reason) in listOf(Protocol.CLOSE_BAD_PROTO to "no hello", Protocol.CLOSE_TRY_AGAIN to "busy")) {
            val first = ServerSide()
            val second = ServerSide()
            server.enqueue(MockResponse().withWebSocketUpgrade(first))
            server.enqueue(MockResponse().withWebSocketUpgrade(second))
            val l = newLink()
            l.start()
            first.opened.poll(5, TimeUnit.SECONDS)!!.close(code, reason)

            val lost = awaitStatus(l) { it.error is LinkError.Busy }
            assertFalse(lost.stopped)
            assertEquals(LinkError.Busy(code, reason), lost.error)
            // First backoff step is 1 s, then the link reconnects on its own.
            assertNotNull(second.opened.poll(5, TimeUnit.SECONDS))
            awaitStatus(l) { it.state == LinkState.STREAMING }
            l.stop()
        }
    }

    @Test
    fun replacedCloseStopsRetrying() {
        val side = ServerSide()
        server.enqueue(MockResponse().withWebSocketUpgrade(side))
        val l = newLink()
        l.start()
        side.opened.poll(5, TimeUnit.SECONDS)!!.close(Protocol.CLOSE_REPLACED, "replaced")

        val status = awaitStatus(l) { it.stopped }
        assertEquals(LinkError.Replaced, status.error)
        assertNoReconnect("4409")
    }

    @Test
    fun unauthorizedSourceCloseStopsRetrying() {
        val side = ServerSide()
        server.enqueue(MockResponse().withWebSocketUpgrade(side))
        val l = newLink()
        l.start()
        side.opened.poll(5, TimeUnit.SECONDS)!!
            .close(Protocol.CLOSE_UNAUTHORIZED, "source token mismatch")

        val status = awaitStatus(l) { it.stopped }
        assertEquals(LinkError.Unauthorized, status.error)
        assertEquals(LinkState.DISCONNECTED, status.state)
        assertNoReconnect("4401")
    }

    @Test
    fun unauthorizedIsReportedAndRetriedWithBackoff() {
        server.enqueue(MockResponse().setResponseCode(401))
        val side = ServerSide()
        server.enqueue(MockResponse().withWebSocketUpgrade(side))
        val l = newLink()
        l.start()

        val failed = awaitStatus(l) { it.error == LinkError.Unauthorized }
        assertFalse(failed.stopped)
        assertEquals(LinkState.DISCONNECTED, failed.state)
        // First backoff step is 1 s, then the second attempt succeeds.
        awaitStatus(l) { it.state == LinkState.STREAMING }
        assertEquals(2, server.requestCount)
    }

    @Test
    fun framesAreNotAdmittedWhileDisconnected() {
        val l = newLink()
        assertFalse(l.admitFrame())
        assertEquals(0L, l.status.value.dropped)
    }

    /**
     * Asserts that no second upgrade request arrives within the first backoff step (1 s) plus
     * margin. Returns as soon as a reconnect shows up instead of sleeping a fixed time.
     */
    private fun assertNoReconnect(code: String) {
        assertNotNull("initial request", server.takeRequest(5, TimeUnit.SECONDS))
        val retry = server.takeRequest(RECONNECT_WINDOW_MS, TimeUnit.MILLISECONDS)
        assertEquals("no reconnect after $code", null, retry)
    }

    private companion object {
        /** First backoff step is 1000 ms; wait past it with margin for a slow CI JVM. */
        const val RECONNECT_WINDOW_MS = 2_500L
    }

    /** Waits until the previous frame has left the socket queue (earlier refusals count as drops). */
    private fun awaitAdmitted(l: OverheadLink) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
        while (!l.admitFrame()) {
            assertTrue("socket queue did not drain", System.nanoTime() < deadline)
            Thread.sleep(10)
        }
    }
}
