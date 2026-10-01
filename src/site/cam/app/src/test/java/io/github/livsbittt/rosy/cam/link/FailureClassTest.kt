package io.github.livsbittt.rosy.cam.link

import java.io.File
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Every case of the shared D-391 vector `test/fixtures/protocol/failure-classes.v1.json` through [FailureClass]. */
class FailureClassTest {
    private val vector: JSONObject by lazy {
        val path = System.getProperty("rosy.failure.vectors")
            ?: error("system property rosy.failure.vectors is not set (see app/build.gradle.kts)")
        JSONObject(File(path).readText(Charsets.UTF_8))
    }

    private fun JSONArray.strings(): List<String> = (0 until length()).map { getString(it) }

    /** What the app's own classifier sees for each transport name: the exception OkHttp hands the listener. */
    private fun exceptionFor(transport: String): Throwable = when (transport) {
        "timeout" -> SocketTimeoutException("connect timed out")
        "no_route" -> NoRouteToHostException("No route to host")
        "connection_refused" -> ConnectException("Failed to connect to /192.168.1.5:8443: Connection refused")
        "dns_failure" -> UnknownHostException("fixture-site.local")
        "tls_handshake" -> SSLHandshakeException("PKIX path building failed")
        "tls_pin_mismatch" -> SSLHandshakeException("handshake failed").apply { initCause(PinMismatchException("fixture")) }
        else -> error("transport $transport has no exception mapping in this test")
    }

    /** One case through the app: ws_close/http_status through FailureClass, transport through NetworkFailure.classify. */
    private fun classify(input: JSONObject): String? = when {
        input.has("ws_close") -> FailureClass.forClose(input.getInt("ws_close"), input.optString("reason").takeIf { input.has("reason") })
        input.has("http_status") -> FailureClass.forHttp(input.getInt("http_status"))
        input.has("transport") -> {
            val name = input.getString("transport")
            val kind = NetworkFailure.classify(exceptionFor(name))
            assertEquals("networkFailureFor($name) disagrees with the classifier", kind, FailureClass.networkFailureFor(name))
            FailureClass.forNetwork(kind)
        }
        input.has("discovery") -> {
            val outcome = input.getString("discovery")
            // The app's not-found path is an exception from SiteDns; it must land on the same class.
            assertEquals(
                FailureClass.forDiscovery(outcome),
                FailureClass.forNetwork(NetworkFailure.classify(SiteNotDiscoveredException("fixture-site.local"))),
            )
            FailureClass.forDiscovery(outcome)
        }
        else -> error("case input has no known kind: $input")
    }

    @Test
    fun everyVectorCase() {
        val cases = vector.getJSONArray("cases")
        assertEquals(28, cases.length())
        val failures = mutableListOf<String>()
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val got = classify(case.getJSONObject("input"))
            if (got != case.getString("expect")) failures += "${case.getString("id")}: expected ${case.getString("expect")}, got $got"
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    @Test
    fun classListMatchesTheVector() {
        assertEquals(vector.getJSONArray("classes").strings(), FailureClass.ALL)
    }

    @Test
    fun closeRetryReasonsAreTheVectors() {
        // Replaces the hardcoded list: the app's 4400 exception must equal close_4400_retry_reasons.
        assertEquals(vector.getJSONArray("close_4400_retry_reasons").strings().toSet(), Protocol.TRANSIENT_4400)
    }

    @Test
    fun fallbacksMatchTheVector() {
        val fallback = vector.getJSONObject("fallback")
        assertEquals(fallback.getString("ws_close"), FailureClass.forClose(1006))
        assertEquals(fallback.getString("http_4xx"), FailureClass.forHttp(418))
        assertEquals(fallback.getString("http_5xx"), FailureClass.forHttp(599))
        assertNull("2xx is not a failure", FailureClass.forHttp(200))
        assertNull("closed vocabulary", FailureClass.networkFailureFor("cosmic_ray"))
        assertNull(FailureClass.forNetwork(NetworkFailure.OTHER))
    }
}
