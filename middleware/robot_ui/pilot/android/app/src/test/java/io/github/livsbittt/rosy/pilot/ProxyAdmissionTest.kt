package io.github.livsbittt.rosy.pilot

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import okhttp3.*
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.Assert.*
import org.junit.Test

class ProxyAdmissionTest {
    @Test fun backgroundSaturationLeavesRoomForControlAndReleasesSlotsAfterResponsesClose() {
        MockWebServer().use { remote ->
            val occupied = CountDownLatch(4); val release = CountDownLatch(1)
            remote.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    if (request.path == "/ws/state") return MockResponse().withWebSocketUpgrade(object : WebSocketListener() {})
                    if (request.path == "/api/v1/vision/front/status") {
                        occupied.countDown(); release.await(5, TimeUnit.SECONDS)
                    }
                    return MockResponse().setBody("{}")
                }
            }
            remote.start()
            val connection = object : PilotConnection {
                override val target = RobotTarget("rosy_01", "127.0.0.1", remote.port, "fixture-token")
                override val secure = false
                override fun authorized() = true
                override fun client() = OkHttpClient()
            }
            val proxy = PilotProxy(connection, BundledAssets { "fixture asset".toByteArray() }, failure = {}).apply { start(5000, false) }
            val browser = OkHttpClient.Builder().callTimeout(1500, TimeUnit.MILLISECONDS).build()
            browser.dispatcher.maxRequestsPerHost = 16
            fun request(path: String) = Request.Builder().url("${proxy.origin}$path")
                .header("Cookie", "${proxy.cookieName}=${proxy.capability}")
                .header("Authorization", "Bearer fixture-token")
            val denied = CountDownLatch(4)
            val completed = CountDownLatch(4)
            val connected = CountDownLatch(4)
            val sockets = (1..4).map {
                browser.newWebSocket(request("/ws/state").header("Origin", proxy.origin).build(), object : WebSocketListener() {
                    override fun onOpen(socket: WebSocket, response: Response) { connected.countDown() }
                    override fun onClosing(socket: WebSocket, code: Int, reason: String) { socket.close(code, "") }
                })
            }
            val callback = object : Callback {
                override fun onFailure(call: Call, error: java.io.IOException) = Unit
                override fun onResponse(call: Call, response: Response) { response.use {
                    if (it.code == 503) denied.countDown()
                    if (it.code == 200) completed.countDown()
                } }
            }
            try {
                assertTrue(connected.await(2, TimeUnit.SECONDS))
                repeat(4) { browser.newCall(request("/api/v1/vision/front/status").build()).enqueue(callback) }
                assertTrue(occupied.await(1, TimeUnit.SECONDS))
                repeat(4) { browser.newCall(request("/api/v1/vision/front/status").build()).enqueue(callback) }
                assertTrue("excess background traffic must fail promptly without using control capacity", denied.await(1, TimeUnit.SECONDS))
                for (path in listOf("/pilot/assets/client.js", "/common/ui.js", "/pilot/bootstrap.js")) {
                    browser.newCall(request(path).build()).execute().use { assertEquals("bundled assets must survive upstream saturation", 200, it.code) }
                }
                val started = System.nanoTime()
                browser.newCall(request("/api/v1/teleop").post("{\"linear\":0,\"angular\":0}".toRequestBody()).build())
                    .execute().use { assertEquals(200, it.code) }
                assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 1000)
                browser.newCall(request("/api/v1/safety/stop").post("{}".toRequestBody()).build())
                    .execute().use { assertEquals(200, it.code) }
                release.countDown()
                assertTrue(completed.await(1, TimeUnit.SECONDS))
                browser.newCall(request("/api/v1/vision/front/status").build()).execute().use { assertEquals(200, it.code) }
            } finally {
                release.countDown(); sockets.forEach { it.cancel() }; browser.dispatcher.cancelAll(); proxy.stop()
                browser.dispatcher.executorService.shutdown(); browser.connectionPool.evictAll()
            }
        }
    }
}
