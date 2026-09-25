package io.github.livsbittt.rosy.overhead.link

import io.github.livsbittt.rosy.overhead.settings.PairingUri
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
