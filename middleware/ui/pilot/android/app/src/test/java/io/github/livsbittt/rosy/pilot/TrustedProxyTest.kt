package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class TrustedProxyTest {
    private fun profile(ca: HeldCertificate, port: Int): PilotProfile = PilotProfile.parse("""
        {"policy":{"mode":"development","site_name":"test","expires_at":"2099-01-01T00:00:00Z","devices":[
        {"device_id":"rosy_01","service_type":"_rosy._tcp","tls_host":"robot-a.local"}]},
        "ca_pem":${JSONObject.quote(ca.certificatePem())},"robots":[
        {"robot_id":"rosy_01","tls_host":"robot-a.local","port":$port,"credential":"private-token-value"}]}
    """.trimIndent())
    @Test fun tlsDnsOverrideRetainsHostnameAndBearer() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val leaf = HeldCertificate.Builder().addSubjectAlternativeName("robot-a.local").signedBy(ca).build()
        val tls = HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build()
        MockWebServer().use { remote ->
            remote.useHttps(tls.sslSocketFactory(), false); remote.start(); remote.enqueue(MockResponse().setBody("{}"))
            val config = profile(ca, remote.port)
            val store = CandidateStore(); val version = store.found("robot")!!
            store.resolved("robot", version, Candidate("robot-a.local", remote.port, listOf("127.0.0.1")))
            val proxy = PilotProxy(config, config.robots.single(), store, {})
            try {
                proxy.start(5000, false)
                OkHttpClient().newCall(Request.Builder().url("${proxy.origin}/api/v1/auth/whoami")
                    .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Authorization", "Bearer private-token-value")
                    .build()).execute().use { assertEquals(200, it.code) }
                val request = remote.takeRequest(2, TimeUnit.SECONDS)!!
                assertEquals("robot-a.local:${remote.port}", request.getHeader("Host"))
                assertEquals("Bearer private-token-value", request.getHeader("Authorization"))
            } finally { proxy.stop() }
        }
    }
    @Test fun wrongTlsNameSendsNoCredential() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val leaf = HeldCertificate.Builder().addSubjectAlternativeName("wrong.local").signedBy(ca).build()
        MockWebServer().use { remote ->
            remote.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            remote.start()
            val config = profile(ca, remote.port)
            val store = CandidateStore(); val version = store.found("robot")!!
            store.resolved("robot", version, Candidate("robot-a.local", remote.port, listOf("127.0.0.1")))
            val proxy = PilotProxy(config, config.robots.single(), store, {})
            try {
                proxy.start(5000, false)
                OkHttpClient().newCall(Request.Builder().url("${proxy.origin}/api/v1/auth/whoami")
                    .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Authorization", "Bearer private-token-value")
                    .build()).execute().use { assertEquals(502, it.code) }
                assertNull(remote.takeRequest(200, TimeUnit.MILLISECONDS))
            } finally { proxy.stop() }
        }
    }
    @Test fun privateOriginRejectsCrossSiteBeforeDial() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val config = profile(ca, 8080)
        val proxy = PilotProxy(config, config.robots.single(), CandidateStore(), {})
        try {
            proxy.start(5000, false)
            OkHttpClient().newCall(Request.Builder().url("${proxy.origin}/api/v1/auth/whoami")
                .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Origin", "https://other.local").build()).execute().use { assertEquals(403, it.code) }
        } finally { proxy.stop() }
    }
    @Test fun websocketRelaysAuthOnlyAfterTlsAndClosesOnRevoke() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val leaf = HeldCertificate.Builder().addSubjectAlternativeName("robot-a.local").signedBy(ca).build()
        val delivered = java.util.concurrent.CountDownLatch(1)
        val closed = java.util.concurrent.CountDownLatch(1)
        val payload = java.util.concurrent.atomic.AtomicReference<String>()
        MockWebServer().use { remote ->
            remote.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            remote.enqueue(MockResponse().withWebSocketUpgrade(object : okhttp3.WebSocketListener() {
                override fun onMessage(socket: okhttp3.WebSocket, text: String) { payload.set(text); delivered.countDown() }
                override fun onClosed(socket: okhttp3.WebSocket, code: Int, reason: String) { closed.countDown() }
                override fun onFailure(socket: okhttp3.WebSocket, error: Throwable, response: okhttp3.Response?) { closed.countDown() }
            })); remote.start()
            val config = profile(ca, remote.port); val store = CandidateStore(); val version = store.found("robot")!!
            store.resolved("robot", version, Candidate("robot-a.local", remote.port, listOf("127.0.0.1")))
            val failures = java.util.concurrent.CopyOnWriteArrayList<String>()
            val proxy = PilotProxy(config, config.robots.single(), store, { failures.add(it) })
            val browser = OkHttpClient()
            try {
                proxy.start(5000, false)
                val auth = "{\"token\":\"private-token-value\"}"
                browser.newWebSocket(Request.Builder().url("${proxy.origin.replace("http:", "ws:")}/ws/control")
                    .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Origin", proxy.origin).build(), object : okhttp3.WebSocketListener() {
                    override fun onOpen(socket: okhttp3.WebSocket, response: okhttp3.Response) { socket.send(auth) }
                })
                assertTrue(delivered.await(5, TimeUnit.SECONDS)); assertEquals(auth, payload.get())
                val request = remote.takeRequest(1, TimeUnit.SECONDS)!!
                assertNull(request.getHeader("Cookie")); assertFalse(request.path!!.contains("private-token"))
                proxy.stop()
                assertTrue("remote socket did not observe revoke", closed.await(3, TimeUnit.SECONDS))
                assertTrue("intentional socket close was reported as lost link: $failures", failures.isEmpty())
            } finally { proxy.stop(); browser.dispatcher.cancelAll(); browser.connectionPool.evictAll(); browser.dispatcher.executorService.shutdown() }
        }
    }
    @Test fun logoutNeverAddsImplicitBearerAndIdentityIsRequiredBeforeUi() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val leaf = HeldCertificate.Builder().addSubjectAlternativeName("robot-a.local").signedBy(ca).build()
        MockWebServer().use { remote ->
            remote.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            remote.start()
            val config = profile(ca, remote.port); val store = CandidateStore(); val version = store.found("robot")!!
            store.resolved("robot", version, Candidate("robot-a.local", remote.port, listOf("127.0.0.1")))
            val proxy = PilotProxy(config, config.robots.single(), store, {})
            try {
                remote.enqueue(MockResponse().setBody("{\"robot_id\":\"rosy_02\"}"))
                assertThrows(IllegalStateException::class.java) { proxy.verifyIdentity() }
                assertEquals("/api/v1/system/info", remote.takeRequest(1, TimeUnit.SECONDS)!!.path)
                proxy.start(5000, false)
                remote.enqueue(MockResponse().setResponseCode(401).setBody("{}"))
                OkHttpClient().newCall(Request.Builder().url("${proxy.origin}/api/v1/auth/whoami")
                    .header("Cookie", "${proxy.cookieName}=${proxy.capability}").build()).execute().use { assertEquals(401, it.code) }
                assertNull(remote.takeRequest(1, TimeUnit.SECONDS)!!.getHeader("Authorization"))
            } finally { proxy.stop() }
            assertNull(remote.takeRequest(100, TimeUnit.MILLISECONDS))
        }
    }
    @Test fun revokeSendsOnlyBoundedZeroAfterVerifiedIdentity() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val leaf = HeldCertificate.Builder().addSubjectAlternativeName("robot-a.local").signedBy(ca).build()
        MockWebServer().use { remote ->
            remote.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            remote.start(); remote.enqueue(MockResponse().setBody("{\"robot_id\":\"rosy_01\"}"))
            val config = profile(ca, remote.port); val store = CandidateStore(); val version = store.found("robot")!!
            store.resolved("robot", version, Candidate("robot-a.local", remote.port, listOf("127.0.0.1")))
            val proxy = PilotProxy(config, config.robots.single(), store, {})
            proxy.verifyIdentity(); remote.takeRequest(1, TimeUnit.SECONDS)
            remote.enqueue(MockResponse().setBody("{}"))
            proxy.stop()
            val stop = remote.takeRequest(1, TimeUnit.SECONDS)!!
            assertEquals("/api/v1/teleop", stop.path)
            assertEquals("POST", stop.method)
            assertEquals("{\"linear\":0,\"angular\":0}", stop.body.readUtf8())
            assertEquals("Bearer private-token-value", stop.getHeader("Authorization"))
        }
    }
    @Test fun cameraProvenanceHeadersReachTheBundledScreens() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val leaf = HeldCertificate.Builder().addSubjectAlternativeName("robot-a.local").signedBy(ca).build()
        MockWebServer().use { remote ->
            remote.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            remote.start(); remote.enqueue(MockResponse()
                .addHeader("Content-Type", "image/jpeg")
                .addHeader("X-Rosy-Camera-Source", "ROSY")
                .addHeader("X-Rosy-Camera-Sequence", "6569")
                .addHeader("X-Rosy-Camera-Captured-At", "1791195119.5")
                .addHeader("X-Rosy-Camera-Frame-Id", "camera_link")
                .addHeader("X-Rosy-Camera-Variant", "raw")
                .setBody("FRAME"))
            val config = profile(ca, remote.port); val store = CandidateStore(); val version = store.found("robot")!!
            store.resolved("robot", version, Candidate("robot-a.local", remote.port, listOf("127.0.0.1")))
            val proxy = PilotProxy(config, config.robots.single(), store, {})
            try {
                proxy.start(5000, false)
                OkHttpClient().newCall(Request.Builder().url("${proxy.origin}/api/v1/vision/front/frame?sequence=6569&overlay=false")
                    .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Authorization", "Bearer private-token-value")
                    .build()).execute().use { response ->
                    assertEquals(200, response.code)
                    // evidence.js fetchCameraPair 검증이 이 다섯 헤더를 필요로 한다.
                    assertEquals("ROSY", response.header("X-Rosy-Camera-Source"))
                    assertEquals("6569", response.header("X-Rosy-Camera-Sequence"))
                    assertEquals("1791195119.5", response.header("X-Rosy-Camera-Captured-At"))
                    assertEquals("camera_link", response.header("X-Rosy-Camera-Frame-Id"))
                    assertEquals("raw", response.header("X-Rosy-Camera-Variant"))
                }
            } finally { proxy.stop() }
        }
    }
    @Test fun transientFailureThenSuccessReportsFailureThenRecovery() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val leaf = HeldCertificate.Builder().addSubjectAlternativeName("robot-a.local").signedBy(ca).build()
        val failures = java.util.concurrent.CopyOnWriteArrayList<String>()
        val recoveries = java.util.concurrent.atomic.AtomicInteger()
        MockWebServer().use { remote ->
            remote.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            remote.dispatcher = object : okhttp3.mockwebserver.Dispatcher() {
                var calls = 0
                override fun dispatch(request: okhttp3.mockwebserver.RecordedRequest): MockResponse {
                    calls += 1
                    // 첫 요청은 응답 없음(프록시 client 의 읽기 시한 2초에 걸림): failure 를 알리고 502 를 내야 한다.
                    if (calls == 1) return MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.NO_RESPONSE)
                    return MockResponse().setBody("{}")
                }
            }
            remote.start()
            // 재시도 없는 짧은 클라이언트로 실패를 결정적으로 만든다(운영 client 은 연결 실패를 재시도한다).
            val connection = object : PilotConnection {
                override val target = RobotTarget("rosy_01", "robot-a.local", remote.port, "private-token-value")
                override val secure = true
                override fun authorized() = true
                override fun client() = OkHttpClient.Builder()
                    .dns(object : okhttp3.Dns {
                        override fun lookup(hostname: String): List<java.net.InetAddress> =
                            listOf(java.net.InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)))
                    })
                    .sslSocketFactory(HandshakeCertificates.Builder().addTrustedCertificate(ca.certificate).build().sslSocketFactory(),
                        HandshakeCertificates.Builder().addTrustedCertificate(ca.certificate).build().trustManager)
                    .retryOnConnectionFailure(false).connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS)
                    .build()
            }
            val proxy = PilotProxy(connection, null,
                { failures.add(it) }, { recoveries.incrementAndGet() })
            try {
                proxy.start(5000, false)
                val call = { OkHttpClient().newCall(Request.Builder().url("${proxy.origin}/api/v1/auth/whoami")
                    .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Authorization", "Bearer private-token-value")
                    .build()).execute().use { it.code } }
                assertEquals(502, call())   // 일시 실패 — 배너에 오류 문구
                assertEquals(200, call())   // 회복 — 배너가 정상 문구로 돌아감
                assertEquals(listOf(LINK_LOST), failures)
                assertEquals(1, recoveries.get())
                call()                      // 이후 성공은 회복을 중복 알리지 않는다
                assertEquals(1, recoveries.get())
            } finally { proxy.stop() }
        }
    }
    @Test fun recordingDownloadLargerThanHtmlCapStreamsIntact() {
        val ca = HeldCertificate.Builder().certificateAuthority(1).build()
        val leaf = HeldCertificate.Builder().addSubjectAlternativeName("robot-a.local").signedBy(ca).build()
        val content = ByteArray(9 * 1024 * 1024) { (it % 127).toByte() }
        MockWebServer().use { remote ->
            remote.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf, ca.certificate).build().sslSocketFactory(), false)
            remote.start(); remote.enqueue(MockResponse().addHeader("Content-Type", "application/x-tar").setBody(okio.Buffer().write(content)))
            val config = profile(ca, remote.port); val store = CandidateStore(); val version = store.found("robot")!!
            store.resolved("robot", version, Candidate("robot-a.local", remote.port, listOf("127.0.0.1")))
            val proxy = PilotProxy(config, config.robots.single(), store, {})
            try {
                proxy.start(5000, false)
                OkHttpClient().newCall(Request.Builder().url("${proxy.origin}/api/v1/recordings/sample/file")
                    .header("Cookie", "${proxy.cookieName}=${proxy.capability}").header("Authorization", "Bearer private-token-value")
                    .build()).execute().use { response -> assertEquals(200, response.code); assertArrayEquals(content, response.body!!.bytes()) }
            } finally { proxy.stop() }
        }
    }
}
