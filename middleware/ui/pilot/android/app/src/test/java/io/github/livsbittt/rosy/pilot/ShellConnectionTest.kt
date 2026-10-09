package io.github.livsbittt.rosy.pilot

import java.io.File
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The app opens one session. The bundled Pilot page receives that session and does not open another. */
class ShellConnectionTest {
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
            val assets = File(System.getProperty("rosy.pilot.assets"))
            val proxy = PilotProxy(session, BundledAssets { path ->
                File(assets, path).takeIf { it.isFile }?.readBytes()
            }, {})
            try {
                proxy.verifyIdentity()
                assertEquals("/api/v1/system/info", remote.takeRequest(1, TimeUnit.SECONDS)!!.path)
                proxy.start(5000, false)
                val browser = OkHttpClient()
                val cookie = "rosy-shell=${proxy.capability}"
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
