package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.link.LinkError
import io.github.livsbittt.rosy.cam.link.NetworkFailure
import io.github.livsbittt.rosy.cam.link.SiteRoute
import io.github.livsbittt.rosy.cam.link.SiteSighting
import io.github.livsbittt.rosy.cam.service.StreamError
import java.net.InetAddress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
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
    fun busyReceiverIsTransientAndNeedsNoSettings() {
        val g = ProblemGuide.forLink(LinkError.Busy(4400, "no hello"), stopped = false, wifiConnected = true)
        assertEquals(Problem.BUSY, g.problem)
        assertEquals(NextStep.NONE, g.step)
        assertEquals("close 4400 no hello", g.detail)
        assertTrue(g.retrying)
    }

    @Test
    fun pinMismatchStopsAndPointsToSettings() {
        val g = ProblemGuide.forLink(network(NetworkFailure.TLS_PIN), stopped = true, wifiConnected = true)
        assertEquals(Problem.TLS_PIN, g.problem)
        assertEquals(NextStep.OPEN_SETTINGS, g.step)
        assertFalse(g.retrying)
        assertTrue(ProblemGuide.stopsCameraFirst(Problem.TLS_PIN, running = true))
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

    private fun lanAt(address: String, prefix: Int, gateway: String?) =
        LanSnapshot.from(listOf(InetAddress.getByName(address) to prefix), gateway?.let { InetAddress.getByName(it) })

    @Test
    fun lanNetworksCountOnlyNetworksThatHoldAnAddress() {
        val lan = LanNetworks()
        lan.onAvailable("wifi-site")
        // Associated, no lease yet: the Wi-Fi icon is on but nothing can connect.
        assertNull(lan.current())
        lan.onLinkProperties("wifi-site", lanAt("192.168.1.37", 24, "192.168.1.1"))
        lan.onAvailable("eth0")
        assertEquals("192.168.1.0/24", lan.current()?.subnet)
        lan.onLost("wifi-site")
        assertNull(lan.current())
        lan.onLost("unknown")
        assertNull(lan.current())
    }

    @Test
    fun lanSnapshotNamesSubnetAndGateway() {
        val lan = lanAt("10.16.36.7", 24, "10.16.36.1")
        assertEquals("10.16.36.0/24", lan.subnet)
        assertEquals("10.16.36.1", lan.gateway)
        assertTrue(lan.connected)
        assertEquals("172.16.0.0/12", LanSnapshot.subnetOf(InetAddress.getByName("172.20.3.4"), 12))
        // A link-local address alone is not connectivity.
        assertFalse(LanSnapshot.from(listOf(InetAddress.getByName("169.254.3.4") to 16), null).connected)
        assertFalse(LanSnapshot.from(listOf(InetAddress.getByName("fe80::1") to 64), null).connected)
    }

    @Test
    fun notDiscoveredAndConflictAreTheirOwnProblems() {
        val missing = ProblemGuide.forLink(network(NetworkFailure.NOT_DISCOVERED), stopped = false, wifiConnected = true)
        assertEquals(Problem.NOT_DISCOVERED, missing.problem)
        assertEquals(NextStep.OPEN_SETTINGS, missing.step)
        assertTrue(missing.retrying)
        val conflict = ProblemGuide.forLink(network(NetworkFailure.CONFLICT), stopped = false, wifiConnected = true)
        assertEquals(Problem.SITE_CONFLICT, conflict.problem)
        assertEquals(NextStep.NONE, conflict.step)
    }

    @Test
    fun manualFallbackFailureAfterAnEmptyBrowseIsNotDiscoveredFirst() {
        // 2026-10-01 tablet: advertiser off, manual address unreachable -> not the generic "닿지 않습니다".
        val afterBrowse = SiteRoute.Manual(InetAddress.getByName("192.168.1.102"))
        for ((kind, manual) in listOf(
            NetworkFailure.UNREACHABLE to Problem.UNREACHABLE,
            NetworkFailure.REFUSED to Problem.REFUSED,
            NetworkFailure.OTHER to Problem.NETWORK_OTHER,
        )) {
            val g = ProblemGuide.forLink(network(kind), stopped = false, wifiConnected = true, route = afterBrowse)
            assertEquals(Problem.NOT_DISCOVERED, g.problem)
            assertEquals(manual, g.manualFailure)
            assertEquals(NextStep.OPEN_SETTINGS, g.step)
            assertEquals("raw detail", g.detail)
        }
    }

    @Test
    fun manualFallbackKeepsItsOwnProblemWhenNotDiscoveryRelated() {
        val afterBrowse = SiteRoute.Manual(InetAddress.getByName("192.168.1.102"))
        // TLS or pin failures mean something answered at the manual address; say that, not "not found".
        assertEquals(Problem.TLS_PIN, ProblemGuide.forLink(network(NetworkFailure.TLS_PIN), true, true, afterBrowse).problem)
        // An IP-only link never browsed, so "not seen on this Wi-Fi" would be a guess.
        val ipOnly = SiteRoute.Manual(InetAddress.getByName("192.168.1.102"), afterBrowse = false)
        val g = ProblemGuide.forLink(network(NetworkFailure.UNREACHABLE), false, true, ipOnly)
        assertEquals(Problem.UNREACHABLE, g.problem)
        assertNull(g.manualFailure)
        // mDNS found the site: an unreachable address is the plain problem.
        val found = SiteRoute.Discovered(SiteSighting("s", "rosy-site.local", 443, listOf(InetAddress.getByName("192.168.1.5"))))
        assertEquals(Problem.UNREACHABLE, ProblemGuide.forLink(network(NetworkFailure.UNREACHABLE), false, true, found).problem)
        // No Wi-Fi still wins.
        assertEquals(Problem.NO_WIFI, ProblemGuide.forLink(network(NetworkFailure.UNREACHABLE), false, false, afterBrowse).problem)
    }

    @Test
    fun notDiscoveredHintComparesTheSubnetWithPairingTime() {
        val other = lanAt("10.16.36.7", 24, "10.16.36.1")
        val site = lanAt("192.168.1.37", 24, "192.168.1.1")
        // 2026-10-01 tablet: same SSID, other AP, 10.16.36.0/24 instead of the site's 192.168.1.0/24.
        assertEquals(ProblemGuide.NotDiscoveredHint.OTHER_NETWORK, ProblemGuide.notDiscoveredHint(other, "192.168.1.0/24"))
        assertEquals(ProblemGuide.NotDiscoveredHint.SAME_NETWORK, ProblemGuide.notDiscoveredHint(site, "192.168.1.0/24"))
        assertEquals(ProblemGuide.NotDiscoveredHint.UNKNOWN, ProblemGuide.notDiscoveredHint(site, null))
        assertEquals(ProblemGuide.NotDiscoveredHint.UNKNOWN, ProblemGuide.notDiscoveredHint(null, "192.168.1.0/24"))
    }
}
