package io.github.livsbittt.rosy.cam.settings

import io.github.livsbittt.rosy.cam.link.certPin
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** D-391 1 site-link record, the shared vector, and the migration of pairings saved before it. */
class SiteLinkTest {
    private val pin = "sha256/" + "A".repeat(43)
    private val otherPin = "sha256/" + "B".repeat(43)

    private val vector: JSONObject by lazy {
        val path = System.getProperty("rosy.sitelink.vectors")
            ?: error("system property rosy.sitelink.vectors is not set (see app/build.gradle.kts)")
        JSONObject(File(path).readText(Charsets.UTF_8))
    }

    private fun JSONArray.strings(): List<String> = (0 until length()).map { getString(it) }

    /** A vector record as the map a JSON reader gives: JSON null is null, numbers stay Int, booleans Boolean. */
    private fun JSONObject.toRecord(): Map<String, Any?> = keys().asSequence().associateWith { key ->
        get(key).takeUnless { it == JSONObject.NULL }
    }

    @Test
    fun everySharedVectorCase() {
        val cases = vector.getJSONArray("cases")
        // The vector declares no count; it only grows, so require cases rather than an exact number.
        assertTrue("site-link vector has no cases", cases.length() > 0)
        val failures = mutableListOf<String>()
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val expect = case.getJSONObject("expect")
            val want = if (expect.getBoolean("valid")) null else expect.getString("reason")
            val got = SiteLinkRecord.validate(case.getJSONObject("record").toRecord())
            if (got != want) failures += "${case.getString("id")}: expected ${want ?: "valid"}, got ${got ?: "valid"}"
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    @Test
    fun reasonsAndRolesMatchTheVector() {
        assertEquals(vector.getJSONArray("reasons").strings(), SiteLinkRecord.REASONS)
        assertEquals(vector.getJSONArray("roles").strings(), SiteLinkRecord.ROLES)
    }

    @Test
    fun everyValidCameraRecordBecomesAValidAppLink() {
        // The app stores a CA pin and the token, not ca_pem and credential/credential_ref (D-391 1 shape vs SiteLink).
        val cases = vector.getJSONArray("cases")
        var adapted = 0
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            if (!case.getJSONObject("expect").getBoolean("valid")) continue
            val record = case.getJSONObject("record").toRecord()
            val link = SiteLinkRecord.toSiteLink(record, token = "camera-token", source = "overhead-1")
            if (record["role"] != SiteLink.ROLE) {
                assertNull("${case.getString("id")}: a robot record is not this app's", link)
                continue
            }
            assertNotNull(case.getString("id"), link)
            link!!
            assertNull("${case.getString("id")}: ${SiteLink.validate(link)}", SiteLink.validate(link))
            val ca = SiteLinkRecord.caCertificates(record["ca_pem"])!!.first()
            assertEquals(certPin(ca.encoded), link.caPin)
            assertEquals((record["tls_host"] as String).lowercase(), link.tlsHost)
            assertEquals(record["expires_at"], link.expiresAt)
            adapted++
        }
        assertTrue("no valid camera record was adapted", adapted > 0)
    }

    @Test
    fun anIpManualHostCarriesOverToTheAppLink() {
        // Shared rule since 464b0c88: manual_host is an IPv4/IPv6 literal, the same as the app's own record.
        val cases = (0 until vector.getJSONArray("cases").length()).map { vector.getJSONArray("cases").getJSONObject(it) }
        for ((id, ip) in listOf("manual_host_ip_allowed" to "192.168.1.20", "manual_host_ipv6_allowed" to "fd00::20")) {
            val record = cases.first { it.getString("id") == id }.getJSONObject("record").toRecord()
            val link = SiteLinkRecord.toSiteLink(record, "t", "overhead-1")!!
            assertEquals(ip, link.manualHost)
            assertNull(SiteLink.validate(link))
        }
    }

    @Test
    fun invalidRecordsAreNotAdapted() {
        val cases = vector.getJSONArray("cases")
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            if (case.getJSONObject("expect").getBoolean("valid")) continue
            assertNull(case.getString("id"), SiteLinkRecord.toSiteLink(case.getJSONObject("record").toRecord(), "t", "overhead-1"))
        }
    }

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
    fun nameLinkClearsTheMigratedManualHost() {
        // 2026-10-01 tablet: a migrated IP pairing, then re-pairing by name with the same CA pin. The old IP
        // must not survive as manual_host, or a missing advertisement dials it instead of saying not_discovered.
        val migrated = SiteLink.from(PairingUri("192.168.1.102", 18448, "tok", "overhead-1", true, pin))
        val renamed = SiteLink.from(PairingUri("perpros.local", 18448, "tok", "overhead-1", true, pin), previous = migrated)
        assertEquals("perpros.local", renamed.tlsHost)
        assertNull(renamed.manualHost)
        assertNull(SiteLink.validate(renamed))
    }

    @Test
    fun onlyAFreshPairingReplacesThePairingSubnet() {
        // Review m6: a settings edit passes no subnet and keeps the pairing-time one; a fresh pairing records its own.
        val saved = SiteLink(null, "rosy-site.local", 443, pin, "t", "overhead-1", secure = true, pairingSubnet = "192.168.1.0/24")
        val edit = SiteLink.from(PairingUri("rosy-site.local", 443, "t", "cam-2", true, pin), pairingSubnet = null, previous = saved)
        assertEquals("192.168.1.0/24", edit.pairingSubnet)
        val fresh = SiteLink.from(PairingUri("rosy-site.local", 443, "t", "overhead-1", true, pin), pairingSubnet = "10.16.36.0/24", previous = saved)
        assertEquals("10.16.36.0/24", fresh.pairingSubnet)
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
    fun hostsCarryingAPortOrJunkAreNotLiteralsAndAreRejected() {
        // Review M1: these passed the old IPv6 regex and crashed InetAddress.getByName on Start.
        for (bad in listOf("192.168.1.5:8443", "1.2.3.4.5:1", "abc:def", "::::", "host:port", "fe80::1%wlan0", "1:2:3:4:5:6:7:8:9")) {
            assertFalse(bad, SiteLink.isIpLiteral(bad))
            assertEquals(bad, "host", PairingUri.validate(bad, 443, "t", "overhead-1"))
        }
        assertEquals(PairingUri.Parsed.Invalid("host"), PairingUri.parse("rosyov://1.2.3.4:5:1/?t=a&s=b"))
    }

    @Test
    fun ipv6LiteralsStillPass() {
        for (good in listOf("::", "::1", "fe80::1", "1:2:3:4:5:6:7:8", "::ffff:192.168.1.5", "2001:db8::8:800:200c:417a")) {
            assertTrue(good, SiteLink.isIpLiteral(good))
            assertNull(good, PairingUri.validate(good, 443, "t", "overhead-1"))
        }
    }

    @Test
    fun tlsHostMustBeASingleLabelLocalName() {
        // D-391 1 decision (2026-10-01): same rule as the shared site-link vector.
        val base = SiteLink(null, "rosy-site.local", 443, pin, "t", "overhead-1", secure = true)
        for (bad in listOf("site.example.org", "rosy-site", "a.b.local", "-x.local", "localhost")) {
            assertEquals(bad, "tls_host", SiteLink.validate(base.copy(tlsHost = bad)))
        }
        // A stored link must already be canonical; only entry is tolerant (it goes through SiteLink.from).
        for (raw in listOf("Rosy-Site.local", "rosy-site.local.", " rosy-site.local")) {
            assertEquals(raw, "tls_host", SiteLink.validate(base.copy(tlsHost = raw)))
        }
        assertNull(SiteLink.entryReason(PairingUri("Rosy-Site.local.", 443, "t", "overhead-1", true, pin)))
        assertEquals("rosy-site.local", SiteLink.from(PairingUri("Rosy-Site.local.", 443, "t", "overhead-1", true, pin)).tlsHost)
    }

    @Test
    fun expiresAtYearZeroIsRejectedLikePython() {
        val valid = (0 until vector.getJSONArray("cases").length()).map { vector.getJSONArray("cases").getJSONObject(it) }
            .first { it.getJSONObject("expect").getBoolean("valid") && it.getJSONObject("record").getString("role") == SiteLink.ROLE }
        val record = valid.getJSONObject("record").toRecord()
        assertNull(SiteLinkRecord.validate(record + ("expires_at" to "0001-01-01T00:00:00Z")))
        assertEquals("bad_expires_at", SiteLinkRecord.validate(record + ("expires_at" to "0000-01-01T00:00:00Z")))
    }

    @Test
    fun entryReasonGuardsTheSettingsFieldAndDeepLinks() {
        assertEquals("tls_host", SiteLink.entryReason(PairingUri("site.example.org", 443, "t", "overhead-1", true, pin)))
        // An IP is still accepted: it becomes the manual address.
        assertNull(SiteLink.entryReason(PairingUri("192.168.1.10", 443, "t", "overhead-1", true, pin)))
        assertNull(SiteLink.entryReason(PairingUri("perpros.local", 18448, "t", "overhead-1", true, pin)))
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
