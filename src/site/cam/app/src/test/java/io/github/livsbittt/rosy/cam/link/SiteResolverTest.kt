package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.net.InetAddress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** D-391 1 re-discovery: mDNS, then `manual_host`, then `not_discovered`, with a fake NSD. */
class SiteResolverTest {
    private val pin = "sha256/" + "A".repeat(43)
    private val site = SiteLink("Rosy site", "rosy-site.local", 443, pin, "t", "overhead-1", secure = true)

    private fun ip(text: String): InetAddress = InetAddress.getByName(text)

    private fun seen(tlsHost: String, vararg addresses: String, name: String = "Rosy site") =
        SiteSighting(name, tlsHost, 443, addresses.map(::ip))

    /** Returns [advertised] filtered by the caller's match, and counts browses. */
    private class FakeBrowser(var advertised: List<SiteSighting>) : SiteBrowser {
        var browses = 0
        var lastTimeoutMs = -1L
        override fun browse(timeoutMs: Long, match: (SiteSighting) -> Boolean): List<SiteSighting> {
            browses++
            lastTimeoutMs = timeoutMs
            return advertised.filter(match)
        }
    }

    @Test
    fun mdnsWinsOverTheManualAddress() {
        val browser = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.5")))
        val route = SiteResolver(site.copy(manualHost = "192.168.1.10"), browser).resolve()
        assertEquals(listOf(ip("192.168.1.5")), (route as SiteRoute.Discovered).sighting.addresses)
        assertEquals(SiteResolver.BROWSE_TIMEOUT_MS, browser.lastTimeoutMs)
    }

    @Test
    fun matchesTlsHostCaseInsensitivelyAndIgnoresOtherSites() {
        val browser = FakeBrowser(listOf(seen("other-site.local", "10.0.0.9", name = "other"), seen("ROSY-SITE.local.", "192.168.1.5")))
        val route = SiteResolver(site, browser).resolve()
        assertEquals(listOf(ip("192.168.1.5")), (route as SiteRoute.Discovered).sighting.addresses)
    }

    @Test
    fun manualAddressOnlyWhenMdnsFindsNothing() {
        val browser = FakeBrowser(listOf(seen("other-site.local", "10.0.0.9", name = "other")))
        val route = SiteResolver(site.copy(manualHost = "192.168.1.10"), browser).resolve()
        assertEquals(SiteRoute.Manual(ip("192.168.1.10")), route)
    }

    @Test
    fun notDiscoveredWithoutAManualAddress() {
        val route = SiteResolver(site, FakeBrowser(emptyList())).resolve()
        assertEquals(SiteRoute.NotDiscovered("rosy-site.local"), route)
    }

    @Test
    fun manualOnlyLinkDialsItsIpWithoutBrowsing() {
        val browser = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.5")))
        val link = site.copy(tlsHost = null, manualHost = "192.168.1.10")
        assertEquals(SiteRoute.Manual(ip("192.168.1.10"), afterBrowse = false), SiteResolver(link, browser).resolve())
        assertEquals(0, browser.browses)
    }

    @Test
    fun nonMdnsNamesGoToTheSystemResolver() {
        val browser = FakeBrowser(emptyList())
        assertEquals(SiteRoute.SystemDns, SiteResolver(site.copy(tlsHost = "site.example.org"), browser).resolve())
        assertEquals(0, browser.browses)
    }

    @Test
    fun discoveryIsCachedBrieflyAndDroppedOnFailure() {
        var now = 0L
        val browser = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.5")))
        val resolver = SiteResolver(site, browser, nowMs = { now })
        resolver.resolve()
        now += SiteResolver.CACHE_MS - 1
        resolver.resolve()
        assertEquals(1, browser.browses)

        // The site moved (DHCP) and the connect failed: the next lookup browses again.
        browser.advertised = listOf(seen("rosy-site.local", "192.168.1.77"))
        resolver.invalidate()
        val moved = resolver.resolve() as SiteRoute.Discovered
        assertEquals(listOf(ip("192.168.1.77")), moved.sighting.addresses)
        assertEquals(2, browser.browses)

        now += SiteResolver.CACHE_MS
        resolver.resolve()
        assertEquals(3, browser.browses)
    }

    @Test
    fun manualFallbackIsNotCached() {
        val browser = FakeBrowser(emptyList())
        val resolver = SiteResolver(site.copy(manualHost = "192.168.1.10"), browser)
        resolver.resolve()
        browser.advertised = listOf(seen("rosy-site.local", "192.168.1.5"))
        assertTrue(resolver.resolve() is SiteRoute.Discovered)
    }

    @Test
    fun sameNameFromTwoAddressesIsAConflict() {
        val browser = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.5"), seen("rosy-site.local", "192.168.1.6", name = "impostor")))
        val route = SiteResolver(site, browser).resolve()
        assertEquals(SiteRoute.Conflict("rosy-site.local", listOf(ip("192.168.1.5"), ip("192.168.1.6"))), route)
    }

    @Test
    fun theSavedSiteNameIsPreferredAmongIdenticalAdvertisements() {
        val browser = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.5", name = "alias"), seen("rosy-site.local", "192.168.1.5")))
        val route = SiteResolver(site, browser).resolve() as SiteRoute.Discovered
        assertEquals("Rosy site", route.sighting.serviceName)
    }

    @Test
    fun routeFlowFollowsTheLastLookup() {
        val resolver = SiteResolver(site.copy(manualHost = "192.168.1.10"), FakeBrowser(emptyList()))
        assertNull(resolver.route.value)
        resolver.resolve()
        assertEquals(SiteRoute.Manual(ip("192.168.1.10")), resolver.route.value)
    }

    @Test
    fun learnsTlsHostOnlyFromTheAdvertisementAtTheManualAddress() {
        val browser = FakeBrowser(listOf(seen("other-site.local", "10.0.0.9", name = "other"), seen("rosy-site.local", "192.168.1.10")))
        val link = site.copy(tlsHost = null, manualHost = "192.168.1.10")
        assertEquals("rosy-site.local", SiteResolver(link, browser).learnTlsHost()?.tlsHost)
        // Unpinned: an advertisement cannot vouch for a name nobody verifies.
        assertNull(SiteResolver(link.copy(caPin = null, secure = false), browser).learnTlsHost())
        // Already named: nothing to learn.
        assertNull(SiteResolver(site, browser).learnTlsHost())
    }

    @Test
    fun siteDnsAnswersOnlyTheTlsHost() {
        val browser = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.5")))
        val system = object : okhttp3.Dns {
            override fun lookup(hostname: String) = listOf(InetAddress.getByAddress(hostname, byteArrayOf(10, 9, 9, 9)))
        }
        val dns = SiteDns("rosy-site.local", SiteResolver(site, browser), system)
        assertEquals(listOf(ip("192.168.1.5")), dns.lookup("rosy-site.local"))
        assertEquals("10.9.9.9", dns.lookup("example.org").single().hostAddress)
    }

    @Test
    fun siteDnsTurnsNotDiscoveredAndConflictIntoOwnFailureClasses() {
        val missing = SiteDns("rosy-site.local", SiteResolver(site, FakeBrowser(emptyList())))
        try {
            missing.lookup("rosy-site.local")
            fail("expected not_discovered")
        } catch (e: SiteNotDiscoveredException) {
            assertEquals(NetworkFailure.NOT_DISCOVERED, NetworkFailure.classify(e))
            assertEquals(FailureClass.NOT_DISCOVERED, FailureClass.forNetwork(NetworkFailure.classify(e)))
        }
        val twice = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.5"), seen("rosy-site.local", "192.168.1.6", name = "b")))
        try {
            SiteDns("rosy-site.local", SiteResolver(site, twice)).lookup("rosy-site.local")
            fail("expected conflict")
        } catch (e: SiteConflictException) {
            assertEquals(NetworkFailure.CONFLICT, NetworkFailure.classify(e))
        }
    }
}
