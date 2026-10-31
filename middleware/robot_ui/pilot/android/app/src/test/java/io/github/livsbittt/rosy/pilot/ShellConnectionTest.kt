package io.github.livsbittt.rosy.pilot

import java.io.File
import java.util.concurrent.TimeUnit
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Each bundled Pilot page receives its selected robot session. */
class ShellConnectionTest {
    @Test fun receiveOnlyStateSocketSurvivesTwoHttpReadTimeouts() {
        MockWebServer().use { remote ->
            remote.start()
            val row = Candidate("127.0.0.1", remote.port, listOf("127.0.0.1"), "Robot", "rosy_01", false)
            val store = CandidateStore().apply { resolved("robot", found("robot")!!, row) }
            val proxy = PilotProxy(LobbySession(RobotTarget("rosy_01", row.host, row.port, "fixture-session-token"),
                false, java.time.Instant.now().plusSeconds(60), row, store), failure = {})
            val stream = Executors.newSingleThreadScheduledExecutor()
            val authenticated = CountDownLatch(1); val closed = CountDownLatch(1)
            val frames = AtomicInteger(); val messages = AtomicInteger()
            remote.enqueue(MockResponse().withWebSocketUpgrade(object : okhttp3.WebSocketListener() {
                override fun onOpen(socket: okhttp3.WebSocket, response: okhttp3.Response) {
                    stream.scheduleAtFixedRate({ socket.send("{\"type\":\"state\"}") }, 0, 100, TimeUnit.MILLISECONDS)
                }
                override fun onMessage(socket: okhttp3.WebSocket, text: String) {
                    messages.incrementAndGet(); authenticated.countDown()
                }
            }))
            val browser = OkHttpClient.Builder().pingInterval(0, TimeUnit.SECONDS).build()
            var socket: okhttp3.WebSocket? = null
            try {
                proxy.start(5000, false)
                socket = browser.newWebSocket(Request.Builder().url("${proxy.origin}/ws/state")
                    .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Origin", proxy.origin).build(),
                    object : okhttp3.WebSocketListener() {
                        override fun onOpen(socket: okhttp3.WebSocket, response: okhttp3.Response) {
                            socket.send("{\"type\":\"auth\",\"token\":\"fixture-session-token\"}")
                        }
                        override fun onMessage(socket: okhttp3.WebSocket, text: String) { frames.incrementAndGet() }
                        override fun onClosing(socket: okhttp3.WebSocket, code: Int, reason: String) { closed.countDown(); socket.close(code, reason) }
                        override fun onClosed(socket: okhttp3.WebSocket, code: Int, reason: String) { closed.countDown() }
                        override fun onFailure(socket: okhttp3.WebSocket, error: Throwable, response: okhttp3.Response?) { closed.countDown() }
                    })
                assertTrue(authenticated.await(3, TimeUnit.SECONDS))
                assertFalse("receive-only telemetry must not hit the HTTP socket idle timeout", closed.await(12, TimeUnit.SECONDS))
                assertTrue(frames.get() >= 100)
                assertEquals("keepalive must not add application or motion messages", 1, messages.get())
                proxy.disconnect()
                assertTrue(closed.await(2, TimeUnit.SECONDS))
            } finally {
                stream.shutdownNow(); socket?.cancel(); proxy.stop()
                browser.dispatcher.cancelAll(); browser.connectionPool.evictAll(); browser.dispatcher.executorService.shutdown()
            }
        }
    }

    @Test fun twoRobotViewsKeepCameraAndTeleopOnTheirOwnRobot() {
        MockWebServer().use { a -> MockWebServer().use { b ->
            a.start(); b.start()
            val first = Candidate("robot-a.local", a.port, listOf("127.0.0.1"), "A", "rosy_01", false)
            val second = Candidate("robot-b.local", b.port, listOf("127.0.0.1"), "B", "rosy_02", false)
            val store = CandidateStore().apply {
                resolved("a", found("a")!!, first); resolved("b", found("b")!!, second)
            }
            val pa = PilotProxy(LobbySession(RobotTarget("rosy_01", first.host, first.port, "first-private-token"),
                false, java.time.Instant.now().plusSeconds(3600), first, store), failure = {})
            val pb = PilotProxy(LobbySession(RobotTarget("rosy_02", second.host, second.port, "second-private-token"),
                false, java.time.Instant.now().plusSeconds(3600), second, store), failure = {})
            val browser = OkHttpClient()
            try {
                a.enqueue(MockResponse().setBody("{\"robot_id\":\"rosy_01\"}"))
                b.enqueue(MockResponse().setBody("{\"robot_id\":\"rosy_02\"}"))
                a.enqueue(MockResponse().setResponseCode(200))
                b.enqueue(MockResponse().setResponseCode(200))
                pa.verifyIdentity(); pb.verifyIdentity()
                for (remote in listOf(a, b)) {
                    assertEquals("/api/v1/system/info", remote.takeRequest(1, TimeUnit.SECONDS)!!.path)
                    assertEquals("/pilot", remote.takeRequest(1, TimeUnit.SECONDS)!!.path)
                }
                pa.start(5000, false); pb.start(5000, false)
                assertFalse(pa.cookieName == pb.cookieName)
                browser.newCall(Request.Builder().url("${pa.origin}/api/v1/vision/front/status")
                    .header("Cookie", "${pb.cookieName}=${pb.capability}").build())
                    .execute().use { assertEquals(403, it.code) }
                assertNull(a.takeRequest(100, TimeUnit.MILLISECONDS))
                for ((remote, proxy, token) in listOf(Triple(a, pa, "first-private-token"), Triple(b, pb, "second-private-token"))) {
                    remote.enqueue(MockResponse().setBody("{\"available\":false}"))
                    browser.newCall(Request.Builder().url("${proxy.origin}/api/v1/vision/front/status")
                        .header("Cookie", "${pa.cookieName}=${pa.capability}; ${pb.cookieName}=${pb.capability}")
                        .header("Authorization", "Bearer $token")
                        .build()).execute().use { assertEquals(200, it.code) }
                    assertEquals("Bearer $token", remote.takeRequest(1, TimeUnit.SECONDS)!!.getHeader("Authorization"))
                    remote.enqueue(MockResponse().setBody("{\"accepted\":true}"))
                    browser.newCall(Request.Builder().url("${proxy.origin}/api/v1/teleop")
                        .header("Cookie", "${pa.cookieName}=${pa.capability}; ${pb.cookieName}=${pb.capability}")
                        .header("Authorization", "Bearer $token")
                        .post("{\"linear\":0,\"angular\":0}".toRequestBody()).build())
                        .execute().use { assertEquals(200, it.code) }
                    assertEquals("Bearer $token", remote.takeRequest(1, TimeUnit.SECONDS)!!.getHeader("Authorization"))
                }
            } finally {
                a.enqueue(MockResponse().setBody("{}")); b.enqueue(MockResponse().setBody("{}"))
                pa.stop(); pb.stop()
                browser.dispatcher.cancelAll(); browser.connectionPool.evictAll(); browser.dispatcher.executorService.shutdown()
            }
            assertEquals("/api/v1/teleop", a.takeRequest(1, TimeUnit.SECONDS)!!.path)
            assertEquals("/api/v1/teleop", b.takeRequest(1, TimeUnit.SECONDS)!!.path)
        } }
    }
    @Test fun developmentSessionReachesBundledPilotWithoutASecondConnect() {
        MockWebServer().use { remote ->
            remote.start()
            val candidate = Candidate("127.0.0.1", remote.port, listOf("127.0.0.1"), "Test robot", "rosy_01", false)
            val store = CandidateStore().apply { resolved("robot", found("robot")!!, candidate) }
            remote.enqueue(MockResponse().setBody("{\"mode\":\"development\",\"robot_id\":\"rosy_01\",\"transport\":\"http\"}"))
            remote.enqueue(MockResponse().setResponseCode(201).setBody(
                "{\"token\":\"session-private-token\",\"role\":\"operator\",\"expires_at\":\"2099-01-01T00:00:00+00:00\"}"))
            val session = LobbyPairing.connect(candidate, LobbyPairing.offer(candidate), store)
            assertEquals("/api/v1/auth/connection", remote.takeRequest(1, TimeUnit.SECONDS)!!.path)
            val join = remote.takeRequest(1, TimeUnit.SECONDS)!!
            assertEquals("/api/v1/auth/development-session", join.path)
            assertEquals("{}", join.body.readUtf8())
            remote.enqueue(MockResponse().setBody("{\"robot_id\":\"rosy_01\"}"))
            remote.enqueue(MockResponse().setResponseCode(200))
            val assets = File(System.getProperty("rosy.pilot.assets"))
            val proxy = PilotProxy(session, BundledAssets { path ->
                File(assets, path).takeIf { it.isFile }?.readBytes()
            }, {})
            try {
                proxy.verifyIdentity()
                assertEquals("/api/v1/system/info", remote.takeRequest(1, TimeUnit.SECONDS)!!.path)
                assertEquals("/pilot", remote.takeRequest(1, TimeUnit.SECONDS)!!.path)
                proxy.start(5000, false)
                val browser = OkHttpClient()
                val cookie = "${proxy.cookieName}=${proxy.capability}"
                browser.newCall(Request.Builder().url("${proxy.origin}/pilot").header("Cookie", cookie).build())
                    .execute().use { page ->
                        assertEquals(200, page.code)
                        val html = page.body!!.string()
                        assertTrue(html.contains("Rosy Pilot"))
                        assertTrue(html.contains("<head><script src=\"/pilot/bootstrap.js\"></script>"))
                    }
                browser.newCall(Request.Builder().url("${proxy.origin}/pilot/bootstrap.js").header("Cookie", cookie).build())
                    .execute().use { script ->
                        val body = script.body!!.string()
                        assertEquals(200, script.code)
                        assertTrue(body.contains("dataset.pilotShell='android'"))
                        assertTrue(body.contains("sessionStorage.setItem('rosy.pilot.token',\"session-private-token\")"))
                        assertFalse(body.contains("development-session"))
                    }
                remote.enqueue(MockResponse().setBody("{\"role\":\"operator\"}"))
                browser.newCall(Request.Builder().url("${proxy.origin}/api/v1/auth/whoami")
                    .header("Cookie", cookie).header("Authorization", "Bearer session-private-token").build())
                    .execute().use { assertEquals(200, it.code) }
                val who = remote.takeRequest(1, TimeUnit.SECONDS)!!
                assertEquals("/api/v1/auth/whoami", who.path)
                assertEquals("Bearer session-private-token", who.getHeader("Authorization"))
                assertNull(remote.takeRequest(200, TimeUnit.MILLISECONDS))
            } finally {
                remote.enqueue(MockResponse().setBody("{}"))
                proxy.stop()
            }
        }
    }
}
