package io.github.livsbittt.rosy.cam.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** D-390 1 site-link record and the migration of pairings saved before it. */
class SiteLinkTest {
    private val pin = "sha256/" + "A".repeat(43)
    private val otherPin = "sha256/" + "B".repeat(43)

    @Test
    fun legacyIpHostBecomesManualHostOnly() {
        val link = SiteLink.from(PairingUri("192.168.1.102", 18447, "tok", "overhead-1", secure = true, pin = pin))
        assertNull(link.tlsHost)
        assertEquals("192.168.1.102", link.manualHost)
        assertEquals("192.168.1.102", link.dialHost)
        assertEquals(pin, link.caPin)
        assertEquals(SiteLink.ROLE, link.role)
        assertNull(SiteLink.validate(link))
    }

    @Test
    fun legacyDnsNameBecomesTlsHost() {
        val link = SiteLink.from(PairingUri("Rosy-Site.local.", 443, "tok", "overhead-1", secure = true, pin = pin))
        assertEquals("rosy-site.local", link.tlsHost)
        assertNull(link.manualHost)
        assertEquals("rosy-site.local", link.toPairing().host)
        assertNull(SiteLink.validate(link))
    }

    @Test
    fun legacyIpv6HostBecomesManualHost() {
        val link = SiteLink.from(PairingUri("fe80::1", 443, "tok", "overhead-1", secure = true, pin = pin))
        assertEquals("fe80::1", link.manualHost)
        assertNull(link.tlsHost)
    }

    @Test
    fun ipLinkForTheSameSiteKeepsTheLearnedTlsHost() {
        val saved = SiteLink(
            siteName = "Rosy site", tlsHost = "rosy-site.local", port = 443, caPin = pin, token = "old",
            source = "overhead-1", secure = true, manualHost = "192.168.1.10", pairingSubnet = "192.168.1.0/24",
        )
        val next = SiteLink.from(PairingUri("192.168.1.20", 443, "new", "overhead-1", true, pin), previous = saved)
        assertEquals("rosy-site.local", next.tlsHost)
        assertEquals("192.168.1.20", next.manualHost)
        assertEquals("Rosy site", next.siteName)
        assertEquals("192.168.1.0/24", next.pairingSubnet)
        assertEquals("new", next.token)
    }

    @Test
    fun anotherSiteInheritsNothing() {
        val saved = SiteLink(
            siteName = "Rosy site", tlsHost = "rosy-site.local", port = 443, caPin = pin, token = "old",
            source = "overhead-1", secure = true, manualHost = "192.168.1.10", pairingSubnet = "192.168.1.0/24",
        )
        val next = SiteLink.from(PairingUri("10.0.0.5", 443, "new", "overhead-1", true, otherPin), previous = saved)
        assertNull(next.tlsHost)
        assertNull(next.siteName)
        assertNull(next.pairingSubnet)
        assertEquals("10.0.0.5", next.manualHost)
    }

    @Test
    fun unpinnedPairingsNeverCountAsTheSameSite() {
        val saved = SiteLink(null, "rosy-site.local", 8095, null, "t", "overhead-1", secure = false)
        val next = SiteLink.from(PairingUri("192.168.1.20", 8095, "t", "overhead-1"), previous = saved)
        assertNull(next.tlsHost)
    }

    @Test
    fun validationRejectsSwappedHostKinds() {
        val base = SiteLink(null, "rosy-site.local", 443, pin, "t", "overhead-1", secure = true)
        assertEquals("tls_host", SiteLink.validate(base.copy(tlsHost = "192.168.1.10")))
        assertEquals("manual_host", SiteLink.validate(base.copy(manualHost = "rosy-site.local")))
        assertEquals("host", SiteLink.validate(base.copy(tlsHost = null)))
        assertEquals("role", SiteLink.validate(base.copy(role = "robot")))
        assertEquals("pin", SiteLink.validate(base.copy(secure = false)))
        assertEquals("token", SiteLink.validate(base.copy(token = "")))
    }

    @Test
    fun ipLiteralDetection() {
        assertTrue(SiteLink.isIpLiteral("10.16.36.7"))
        assertTrue(SiteLink.isIpLiteral("::1"))
        assertFalse(SiteLink.isIpLiteral("256.1.1.1"))
        assertFalse(SiteLink.isIpLiteral("rosy-site.local"))
        assertFalse(SiteLink.isIpLiteral("10.16.36"))
    }

    @Test
    fun toStringRedactsTheToken() {
        val text = SiteLink(null, "rosy-site.local", 443, pin, "s3cret-token", "overhead-1", secure = true).toString()
        assertFalse(text.contains("s3cret-token"))
    }
}
