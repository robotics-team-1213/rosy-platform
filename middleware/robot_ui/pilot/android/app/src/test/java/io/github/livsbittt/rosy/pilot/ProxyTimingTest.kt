package io.github.livsbittt.rosy.pilot

import java.net.ServerSocket
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import okio.Source
import okio.Timeout
import okio.buffer
import org.junit.Assert.*
import org.junit.Test

class ProxyTimingTest {
    private fun proxy(port: Int, timeoutMs: Long = 8000, readTimeoutMs: Long = 5000): PilotProxy {
        val connection = object : PilotConnection {
            override val target = RobotTarget("rosy_01", "127.0.0.1", port, "fixture-token")
            override val secure = false
            override fun authorized() = true
            override fun client() = OkHttpClient.Builder().callTimeout(timeoutMs, TimeUnit.MILLISECONDS)
                .readTimeout(readTimeoutMs, TimeUnit.MILLISECONDS).build()
        }
        return PilotProxy(connection, failure = {}).apply { start(5000, false) }
    }

    private fun request(proxy: PilotProxy, path: String) = Request.Builder().url("${proxy.origin}$path")
        .header("Cookie", "${proxy.cookieName}=${proxy.capability}")
        .header("Authorization", "Bearer fixture-token")

    @Test fun stalledTeleopExpiresBeforeItCanOccupyProxyForSeconds() {
        MockWebServer().use { remote ->
            remote.start()
            remote.enqueue(MockResponse().setHeadersDelay(1500, TimeUnit.MILLISECONDS).setBody("{}"))
            remote.enqueue(MockResponse().setBody("{\"accepted\":true}"))
            val proxy = proxy(remote.port)
            val browser = OkHttpClient()
            try {
                val started = System.nanoTime()
                browser.newCall(request(proxy, "/api/v1/teleop").post("{\"linear\":0,\"angular\":0}".toRequestBody()).build())
                    .execute().use { assertEquals(502, it.code) }
                assertTrue("upstream must share the 400ms motion deadline", TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 1000)
                browser.newCall(request(proxy, "/api/v1/teleop").post("{\"linear\":0,\"angular\":0}".toRequestBody()).build())
                    .execute().use { assertEquals(200, it.code) }
                assertEquals(2, remote.requestCount)
            } finally {
                proxy.stop(); browser.dispatcher.executorService.shutdown(); browser.connectionPool.evictAll()
            }
        }
    }

    @Test fun activeCameraStreamOutlivesOrdinaryCallDeadlineWithoutBlockingTeleop() {
        MockWebServer().use { remote ->
            remote.start()
            val bytes = ByteArray(1200) { 42 }
            remote.enqueue(MockResponse().setHeader("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                .setBody(Buffer().write(bytes)).throttleBody(100, 100, TimeUnit.MILLISECONDS))
            remote.enqueue(MockResponse().setBody("{}"))
            val proxy = proxy(remote.port, 300)
            val browser = OkHttpClient()
            try {
                browser.newCall(request(proxy, "/api/v1/vision/front/stream").build()).execute().use { response ->
                    val started = System.nanoTime()
                    browser.newCall(request(proxy, "/api/v1/teleop").post("{\"linear\":0,\"angular\":0}".toRequestBody()).build())
                        .execute().use { assertEquals(200, it.code) }
                    assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 1000)
                    assertArrayEquals(bytes, response.body!!.bytes())
                }
            } finally {
                proxy.stop(); browser.dispatcher.executorService.shutdown(); browser.connectionPool.evictAll()
            }
        }
    }

    @Test fun stalledCameraStillHitsItsReadDeadline() {
        MockWebServer().use { remote ->
            remote.start()
            remote.enqueue(MockResponse().setHeader("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                .setBody("frame").setBodyDelay(1500, TimeUnit.MILLISECONDS))
            val proxy = proxy(remote.port, readTimeoutMs = 200)
            val browser = OkHttpClient()
            try {
                val started = System.nanoTime()
                browser.newCall(request(proxy, "/api/v1/vision/front/stream").build()).execute().use { response ->
                    assertThrows(java.io.IOException::class.java) { response.body!!.bytes() }
                }
                assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 1000)
                assertTrue(proxy.diagnosticSummary().lineSequence().first { it.startsWith("영상:") }.contains("오류 1/1"))
            } finally {
                proxy.stop(); browser.dispatcher.executorService.shutdown(); browser.connectionPool.evictAll()
            }
        }
    }

    @Test fun continuousCameraExceedsDownloadBudgetWhileFiniteDownloadsRemainBounded() {
        val budget = 257L * 1024 * 1024
        val connection = object : PilotConnection {
            override val target = RobotTarget("rosy_01", "127.0.0.1", 8080, "fixture-token")
            override val secure = false
            override fun authorized() = true
            override fun client() = OkHttpClient.Builder().addInterceptor { chain ->
                val live = chain.request().url.encodedPath.endsWith("/stream")
                val body = object : okhttp3.ResponseBody() {
                    private val data = object : Source {
                        private var remaining = budget
                        private val chunk = ByteArray(8192)
                        override fun timeout() = Timeout.NONE
                        override fun close() = Unit
                        override fun read(sink: Buffer, byteCount: Long): Long {
                            if (remaining == 0L) return -1
                            val size = minOf(byteCount, chunk.size.toLong(), remaining).toInt()
                            sink.write(chunk, 0, size); remaining -= size
                            return size.toLong()
                        }
                    }.buffer()
                    override fun contentType() = null
                    override fun contentLength() = if (live) -1L else budget
                    override fun source() = data
                }
                okhttp3.Response.Builder().request(chain.request()).protocol(okhttp3.Protocol.HTTP_1_1)
                    .code(200).message("OK").header("Content-Type", if (live) "multipart/x-mixed-replace" else "application/octet-stream")
                    .body(body).build()
            }.build()
        }
        val proxy = PilotProxy(connection, failure = {}).apply { start(5000, false) }
        val browser = OkHttpClient()
        try {
            browser.newCall(request(proxy, "/api/v1/vision/front/stream").build()).execute().use { response ->
                var received = 0L
                val buffer = Buffer()
                val source = response.body!!.source()
                while (true) {
                    val count = source.read(buffer, 32768)
                    if (count < 0) break
                    received += count; buffer.clear()
                }
                assertEquals(budget, received)
            }
            browser.newCall(request(proxy, "/api/v1/vision/front/frame").build()).execute().use { assertEquals(413, it.code) }
        } finally {
            proxy.stop(); browser.dispatcher.executorService.shutdown(); browser.connectionPool.evictAll()
        }
    }

    @Test fun silentRobotSocketIsProbedAndDisconnectedEvenWhileBrowserAnswersPings() {
        ServerSocket(0).use { remote ->
            val release = CountDownLatch(1); val ping = CountDownLatch(1); val closed = CountDownLatch(1)
            val opcode = AtomicInteger()
            val server = Thread {
                remote.accept().use { peer ->
                    peer.soTimeout = 7000
                    val input = peer.getInputStream()
                    val reader = input.bufferedReader()
                    var key = ""
                    while (true) {
                        val line = reader.readLine() ?: break
                        if (line.isEmpty()) break
                        if (line.startsWith("Sec-WebSocket-Key:", true)) key = line.substringAfter(':').trim()
                    }
                    val accept = Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1")
                        .digest((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").toByteArray()))
                    peer.getOutputStream().apply {
                        write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: $accept\r\n\r\n".toByteArray()); flush()
                    }
                    try { opcode.set(input.read() and 15); ping.countDown(); release.await(8, TimeUnit.SECONDS) }
                    catch (_: java.io.IOException) { /* RED has no upstream ping. */ }
                }
            }.apply { isDaemon = true; start() }
            val proxy = proxy(remote.localPort)
            val browser = OkHttpClient()
            val socket = browser.newWebSocket(request(proxy, "/ws/state").header("Origin", proxy.origin).build(),
                object : okhttp3.WebSocketListener() {
                    override fun onClosing(socket: okhttp3.WebSocket, code: Int, reason: String) { closed.countDown(); socket.close(code, reason) }
                    override fun onFailure(socket: okhttp3.WebSocket, error: Throwable, response: okhttp3.Response?) { closed.countDown() }
                })
            try {
                assertTrue("the robot leg needs its own protocol heartbeat", ping.await(3, TimeUnit.SECONDS))
                assertEquals(9, opcode.get())
                assertTrue("missing robot pong must terminate the browser relay", closed.await(4, TimeUnit.SECONDS))
            } finally {
                release.countDown(); socket.cancel(); proxy.stop(); server.join(1000)
                browser.dispatcher.executorService.shutdown(); browser.connectionPool.evictAll()
            }
        }
    }
}
