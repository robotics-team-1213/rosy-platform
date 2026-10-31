package io.github.livsbittt.rosy.pilot

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class ProxyCloseTest {
    @Test fun robotClosurePreservesAuthCodesAndAcknowledgesRobotWithoutLeakingReason() {
        for (code in listOf(4401, 4403, 1000)) MockWebServer().use { remote ->
            remote.start()
            val ended = CountDownLatch(1); val browserEnded = CountDownLatch(1)
            val received = AtomicInteger()
            remote.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
                override fun onOpen(socket: WebSocket, response: okhttp3.Response) { socket.close(code, "private-server-detail") }
                override fun onClosed(socket: WebSocket, code: Int, reason: String) { ended.countDown() }
            }))
            val connection = object : PilotConnection {
                override val target = RobotTarget("rosy_01", "127.0.0.1", remote.port, "fixture-token")
                override val secure = false
                override fun authorized() = true
                override fun client() = OkHttpClient()
            }
            val proxy = PilotProxy(connection, failure = {}).apply { start(5000, false) }
            val browser = OkHttpClient()
            val socket = browser.newWebSocket(Request.Builder().url("${proxy.origin}/ws/state")
                .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Origin", proxy.origin).build(),
                object : WebSocketListener() {
                    override fun onClosing(socket: WebSocket, code: Int, reason: String) {
                        received.set(code); assertFalse(reason.contains("private-server-detail"))
                        socket.close(code, ""); browserEnded.countDown()
                    }
                })
            try {
                assertTrue("robot closure must promptly reach the browser", browserEnded.await(2, TimeUnit.SECONDS))
                assertEquals(code, received.get())
                assertTrue("robot close handshake must finish", ended.await(2, TimeUnit.SECONDS))
            } finally {
                socket.cancel(); proxy.stop()
                browser.dispatcher.executorService.shutdown(); browser.connectionPool.evictAll()
            }
        }
    }
}
