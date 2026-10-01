package io.github.livsbittt.rosy.cam.link

import java.io.File
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import io.github.livsbittt.rosy.cam.ui.NextStep
import io.github.livsbittt.rosy.cam.ui.Problem
import io.github.livsbittt.rosy.cam.ui.ProblemGuide
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
        // The vector declares no count; it only grows, so require cases rather than an exact number.
        assertTrue("failure-classes vector has no cases", cases.length() > 0)
        val failures = mutableListOf<String>()
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val got = classify(case.getJSONObject("input"))
            if (got != case.getString("expect")) failures += "${case.getString("id")}: expected ${case.getString("expect")}, got $got"
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    /**
     * What the link does for each class of a WS close (OverheadLink.closeOutcome): true = stop for good.
     * `forbidden` (4403) is final by rosy-00's decision (2026-10-01): the credential is valid but not allowed,
     * so retrying cannot help. It stops without a re-pair prompt (see [forbiddenStopsWithoutARePairPrompt]).
     */
    private val closeBehaviour = mapOf(
        FailureClass.AUTH_FINAL to true,
        FailureClass.PROTOCOL_MISMATCH to true,
        FailureClass.CONFLICT to true,
        FailureClass.FORBIDDEN to true,
        FailureClass.AUTH_RETRY to false,
        FailureClass.BUSY to false,
        FailureClass.UNREACHABLE to false,
    )

    @Test
    fun closeBehaviourAgreesWithTheClassOfEveryWsCase() {
        val cases = vector.getJSONArray("cases")
        var checked = 0
        val failures = mutableListOf<String>()
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val input = case.getJSONObject("input")
            if (!input.has("ws_close")) continue
            val code = input.getInt("ws_close")
            val reason = if (input.has("reason")) input.getString("reason") else ""
            val expected = closeBehaviour[case.getString("expect")]
                ?: error("${case.getString("id")}: no behaviour row for class ${case.getString("expect")}")
            val (_, fatal) = OverheadLink.closeOutcome(code, reason)
            if (fatal != expected) failures += "${case.getString("id")}: class ${case.getString("expect")} expects fatal=$expected, link says $fatal"
            checked++
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
        assertTrue("no ws_close cases", checked > 0)
    }

    @Test
    fun forbiddenStopsWithoutARePairPrompt() {
        val (error, fatal) = OverheadLink.closeOutcome(Protocol.CLOSE_FORBIDDEN, "")
        assertEquals(LinkError.Forbidden, error)
        assertTrue(fatal)
        val guidance = ProblemGuide.forLink(error, stopped = true, wifiConnected = true)
        assertEquals(Problem.FORBIDDEN, guidance.problem)
        assertEquals("no settings / re-pair button for 4403", NextStep.NONE, guidance.step)
        assertFalse(ProblemGuide.stopsCameraFirst(Problem.FORBIDDEN, running = true))
        // Re-pair stays only for auth_final (4401).
        assertEquals(NextStep.OPEN_SETTINGS, ProblemGuide.forLink(LinkError.Unauthorized, true, true).step)
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
