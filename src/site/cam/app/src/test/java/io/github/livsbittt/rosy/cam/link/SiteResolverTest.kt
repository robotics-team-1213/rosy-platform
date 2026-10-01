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
    fun anUnparseableManualAddressNeverThrows() {
        // Review M1: a record saved before the strict literal check must not crash Start.
        val stale = site.copy(tlsHost = null, manualHost = "192.168.1.5:8443")
        assertEquals(SiteRoute.NotDiscovered("192.168.1.5:8443"), SiteResolver(stale, FakeBrowser(emptyList())).resolve())
        val named = site.copy(manualHost = "abc:def")
        assertEquals(SiteRoute.NotDiscovered("rosy-site.local"), SiteResolver(named, FakeBrowser(emptyList())).resolve())
    }

    @Test
    fun siteDnsTurnsAResolverCrashIntoALookupFailure() {
        val boom = SiteBrowser { _, _ -> throw IllegalStateException("nsd died") }
        try {
            SiteDns("rosy-site.local", SiteResolver(site, boom)).lookup("rosy-site.local")
            fail("expected UnknownHostException")
        } catch (e: java.net.UnknownHostException) {
            assertTrue(e.message.orEmpty().contains("nsd died"))
        }
    }

    @Test
    fun aNonLocalTlsHostIsNeverBrowsedNorHandedToSystemDns() {
        // D-391 1 decision (2026-10-01): tls_host is a .local name; the review m4 system-DNS path is gone.
        // SiteLink.validate rejects such a record, so this is only the resolver's own guard.
        var systemCalls = 0
        val system = object : okhttp3.Dns {
            override fun lookup(hostname: String): List<InetAddress> {
                systemCalls++
                return listOf(ip("10.9.9.9"))
            }
        }
        val browser = FakeBrowser(listOf(seen("site.example.org", "192.168.1.5")))
        val named = site.copy(tlsHost = "site.example.org")
        assertEquals(SiteRoute.NotDiscovered("site.example.org"), SiteResolver(named, browser).resolve())
        try {
            SiteDns("site.example.org", SiteResolver(named, browser), system).lookup("site.example.org")
            fail("expected not_discovered")
        } catch (e: SiteNotDiscoveredException) {
            assertEquals(NetworkFailure.NOT_DISCOVERED, NetworkFailure.classify(e))
        }
        val withManual = named.copy(manualHost = "192.168.1.10")
        assertEquals(listOf(ip("192.168.1.10")), SiteDns("site.example.org", SiteResolver(withManual, browser), system).lookup("site.example.org"))
        assertEquals(0, browser.browses)
        assertEquals(0, systemCalls)
    }

    @Test
    fun anUnpinnedLinkNeverDialsAnAdvertisedAddress() {
        // Review m3: without a pinned CA nothing authenticates an mDNS responder.
        val browser = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.5")))
        val unpinned = site.copy(caPin = null, secure = false)
        assertEquals(SiteRoute.NotDiscovered("rosy-site.local"), SiteResolver(unpinned, browser).resolve())
        val withManual = unpinned.copy(manualHost = "192.168.1.10")
        assertEquals(SiteRoute.Manual(ip("192.168.1.10"), afterBrowse = false), SiteResolver(withManual, browser).resolve())
        assertEquals(0, browser.browses)
    }

    @Test
    fun invalidateNeverWaitsForABrowseInProgress() {
        // Review m2: invalidate() runs on OkHttp's callback thread and must not block behind a 5 s browse.
        val entered = java.util.concurrent.CountDownLatch(1)
        val release = java.util.concurrent.CountDownLatch(1)
        val slow = SiteBrowser { _, _ ->
            entered.countDown()
            release.await(10, java.util.concurrent.TimeUnit.SECONDS)
            emptyList()
        }
        val resolver = SiteResolver(site, slow)
        val lookup = Thread { resolver.resolve() }.apply { start() }
        try {
            assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
            val done = java.util.concurrent.CountDownLatch(1)
            Thread { resolver.invalidate(); done.countDown() }.start()
            assertTrue("invalidate blocked behind the browse", done.await(1, java.util.concurrent.TimeUnit.SECONDS))
        } finally {
            release.countDown()
            lookup.join(5_000)
        }
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
        assertEquals(
            SiteRoute.Conflict("rosy-site.local", listOf(ip("192.168.1.5"), ip("192.168.1.6")), listOf("Rosy site", "impostor")),
            route,
        )
    }

    @Test
    fun overlappingAddressSetsAreTheSameHostNotAConflict() {
        // Review m5: one instance seen with IPv4 only and again with IPv4 + IPv6.
        val browser = FakeBrowser(
            listOf(seen("rosy-site.local", "192.168.1.5"), seen("rosy-site.local", "192.168.1.5", "fd00::5", name = "Rosy site v6")),
        )
        val route = SiteResolver(site, browser).resolve()
        assertTrue(route.toString(), route is SiteRoute.Discovered)
        assertEquals("Rosy site", (route as SiteRoute.Discovered).sighting.serviceName)
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
        // Two adverts at the same IP (review M2): ambiguous, learn nothing.
        val two = FakeBrowser(listOf(seen("rosy-site.local", "192.168.1.10"), seen("evil.local", "192.168.1.10", name = "evil")))
        assertNull(SiteResolver(link, two).learnTlsHost())
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
