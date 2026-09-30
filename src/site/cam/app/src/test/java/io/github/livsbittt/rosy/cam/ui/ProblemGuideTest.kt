package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.link.LinkError
import io.github.livsbittt.rosy.cam.link.NetworkFailure
import io.github.livsbittt.rosy.cam.service.StreamError
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProblemGuideTest {
    private fun network(kind: NetworkFailure) = LinkError.Network("raw detail", kind)

    @Test
    fun unreachableOffersSettingsAndKeepsTheRawDetail() {
        val g = ProblemGuide.forLink(network(NetworkFailure.UNREACHABLE), stopped = false, wifiConnected = true)
        assertEquals(Problem.UNREACHABLE, g.problem)
        assertEquals(NextStep.OPEN_SETTINGS, g.step)
        assertEquals("raw detail", g.detail)
        assertTrue(g.retrying)
    }

    @Test
    fun anyTransportFailureWithoutWifiIsNoWifi() {
        for (kind in NetworkFailure.entries) {
            val g = ProblemGuide.forLink(network(kind), stopped = false, wifiConnected = false)
            assertEquals(Problem.NO_WIFI, g.problem)
            assertEquals(NextStep.OPEN_SETTINGS, g.step)
        }
    }

    @Test
    fun refusedMeansTheReceiverIsOffSoSettingsWontHelp() {
        val g = ProblemGuide.forLink(network(NetworkFailure.REFUSED), stopped = false, wifiConnected = true)
        assertEquals(Problem.REFUSED, g.problem)
        assertEquals(NextStep.NONE, g.step)
    }

    @Test
    fun tlsAndUnknownHostOfferSettings() {
        assertEquals(Problem.TLS, ProblemGuide.forLink(network(NetworkFailure.TLS), false, true).problem)
        val host = ProblemGuide.forLink(network(NetworkFailure.UNKNOWN_HOST), false, true)
        assertEquals(Problem.UNKNOWN_HOST, host.problem)
        assertEquals(NextStep.OPEN_SETTINGS, host.step)
    }

    @Test
    fun tokenAndDuplicateSourcePointToSettings() {
        val token = ProblemGuide.forLink(LinkError.Unauthorized, stopped = true, wifiConnected = true)
        assertEquals(Problem.UNAUTHORIZED, token.problem)
        assertEquals(NextStep.OPEN_SETTINGS, token.step)
        assertFalse(token.retrying)
        val dup = ProblemGuide.forLink(LinkError.Replaced, stopped = true, wifiConnected = true)
        assertEquals(Problem.REPLACED, dup.problem)
        assertEquals("close 4409", dup.detail)
        assertFalse(dup.retrying)
    }

    @Test
    fun protocolErrorsIgnoreWifiState() {
        // Only transport failures are blamed on missing Wi-Fi.
        assertEquals(Problem.PROTOCOL_MISMATCH, ProblemGuide.forLink(LinkError.ProtocolMismatch, true, false).problem)
        assertEquals(Problem.CLOSED, ProblemGuide.forLink(LinkError.Closed(1011, "boom"), false, false).problem)
        assertEquals("close 1011 boom", ProblemGuide.forLink(LinkError.Closed(1011, "boom"), false, true).detail)
    }

    @Test
    fun sessionErrors() {
        assertEquals(NextStep.OPEN_SETTINGS, ProblemGuide.forStream(StreamError.NotPaired).step)
        val cam = ProblemGuide.forStream(StreamError.Camera("CAMERA_IN_USE"))
        assertEquals(Problem.CAMERA, cam.problem)
        assertEquals("CAMERA_IN_USE", cam.detail)
    }

    @Test
    fun tokenAndNameProblemsStopTheCameraFirstOnlyWhileRunning() {
        assertTrue(ProblemGuide.stopsCameraFirst(Problem.UNAUTHORIZED, running = true))
        assertTrue(ProblemGuide.stopsCameraFirst(Problem.REPLACED, running = true))
        assertFalse(ProblemGuide.stopsCameraFirst(Problem.UNAUTHORIZED, running = false))
        assertFalse(ProblemGuide.stopsCameraFirst(Problem.UNREACHABLE, running = true))
    }

    @Test
    fun lanNetworksStayConnectedUntilTheLastOneIsLost() {
        val lan = LanNetworks()
        assertTrue(lan.onAvailable("wifi-site"))
        assertTrue(lan.onAvailable("eth0"))
        assertTrue(lan.onLost("eth0"))
        assertFalse(lan.onLost("wifi-site"))
        assertFalse(lan.onLost("unknown"))
    }
}
