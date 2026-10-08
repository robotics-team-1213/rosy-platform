package io.github.livsbittt.rosy.pilot

import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test

/**
 * Opt-in page probe. The default unit run skips it.
 * A browser test sets rosy.pilot.page.probe and drives the bundled page through this proxy.
 */
class ShellPageProbe {
    @Test fun bundledPageThroughTheAppProxy() {
        assumeTrue(System.getProperty("rosy.pilot.page.probe") == "1")
        val dir = File(System.getProperty("rosy.pilot.page.dir"))
        check(dir.isDirectory) { "probe directory missing" }
        val address = File(dir, "address.txt")
        val done = File(dir, "done")
        val log = File(dir, "upstream.log")
        address.delete()
        done.delete()
        log.writeText("")

        val sessions = AtomicInteger()
        MockWebServer().use { remote ->
            remote.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    log.appendText("${request.method} ${request.path}\n")
                    return core(request, sessions)
                }
            }
            remote.start()
            var proxy: PilotProxy? = null
            try {
                val candidate = Candidate("127.0.0.1", remote.port, listOf("127.0.0.1"), "Test robot", "rosy_01", false)
                val store = CandidateStore().apply { resolved("robot", found("robot")!!, candidate) }
                val session = LobbyPairing.connect(candidate, LobbyPairing.offer(candidate), store)
                val opened = sessions.get()
                val assets = File(System.getProperty("rosy.pilot.assets"))
                val bundle = BundledAssets { path -> File(assets, path).takeIf { it.isFile }?.readBytes() }
                run probe@{
                    repeat(8) {
                        val attempt = PilotProxy(session, bundle, {})
                        attempt.verifyIdentity()
                        attempt.start(5000, false)
                        if (attempt.listeningPort !in CHROMIUM_UNSAFE_PORTS) {
                            proxy = attempt
                            return@probe
                        }
                        attempt.stop()
                    }
                }
                val ready = checkNotNull(proxy) { "no Chromium-safe proxy port" }
                address.writeText("${ready.origin}\n${ready.capability}\n")
                val deadline = System.nanoTime() + 120_000_000_000L
                while (!done.exists()) {
                    check(System.nanoTime() < deadline) { "page probe timed out" }
                    Thread.sleep(100)
                }
                assertEquals(opened, sessions.get())
            } finally {
                proxy?.stop()
            }
        }
    }

    private fun core(request: RecordedRequest, sessions: AtomicInteger): MockResponse {
        val path = request.path.orEmpty().substringBefore('?')
        val method = request.method.orEmpty()
        if (method == "POST" && (path == "/api/v1/auth/development-session" || path == "/api/v1/auth/pair")) {
            sessions.incrementAndGet()
        }
        val authed = request.getHeader("Authorization") == "Bearer $TOKEN"
        val body = when {
            path == "/api/v1/auth/connection" && method == "GET" ->
                """{"mode":"development","robot_id":"rosy_01","transport":"http"}"""
            path == "/api/v1/auth/development-session" && method == "POST" ->
                """{"token":"$TOKEN","role":"operator","expires_at":"2099-01-01T00:00:00+00:00"}"""
            path == "/api/v1/system/info" && method == "GET" && authed -> """{"robot_id":"rosy_01"}"""
            path == "/api/v1/auth/whoami" && method == "GET" && authed ->
                """{"id":"dev-1","role":"operator","label":"operator","source":"dev","created_at":"","expires_at":null}"""
            path == "/api/v1/system/capabilities" && method == "GET" && authed -> CAPABILITIES
            path == "/api/v1/robot/state" && method == "GET" && authed -> STATE
            path == "/api/v1/mode" && method == "POST" && authed -> """{"mode":"MANUAL"}"""
            path == "/api/v1/teleop" && method == "POST" && authed -> "{}"
            else -> null
        }
        val code = when {
            body != null && path == "/api/v1/auth/development-session" -> 201
            body != null -> 200
            path == "/api/v1/sim/omx/target" -> 404
            path.startsWith("/api/v1/") && !authed && path != "/api/v1/auth/connection" -> 401
            else -> 404
        }
        return MockResponse().setResponseCode(code).setHeader("Content-Type", "application/json")
            .setBody(body ?: """{"detail":"not found"}""")
    }

    private companion object {
        const val TOKEN = "session-private-token"
        const val CAPABILITIES = """{"teleop":true,"withheld":{"reasons":{}},"runtime":{"hardware":true,"evidence":true,"drive":true,"navigation":false,"maps":false},"controls":{"schema":"rosy.controls/1","items":[{"id":"base","kind":"base_velocity","label":"drive","max_linear":0.15,"max_angular":0.6,"pivot":true,"fine":true,"autonomy":["line"]}]}}"""
        const val STATE = """{"timestamp":"2026-10-08T00:00:00Z","mode":"IDLE","velocity":{"linear":0.0,"angular":0.0},"battery":{"percent":84,"volts":7.6},"activity":null,"evidence":{"velocity":{"received_at":"2026-10-08T00:00:00Z","evidence":"fresh"},"battery":{"received_at":"2026-10-08T00:00:00Z","evidence":"fresh"}}}"""
        val CHROMIUM_UNSAFE_PORTS = setOf(
            1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060, 5061, 6000, 6566,
            6665, 6666, 6667, 6668, 6669, 6679, 6697, 10080,
        )
    }
}
