package io.github.livsbittt.rosy.cam.settings

import io.github.livsbittt.rosy.cam.settings.SiteLinkPrefs as K
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

/** DataStore key layout, migration from the pre-D-391 keys, and what a write leaves behind (review m9). */
class SiteLinkPrefsTest {
    private val pin = "sha256/" + "A".repeat(43)

    private fun legacy(host: String, pin: String? = this.pin): Map<String, Any?> = buildMap {
        put(K.LEGACY_HOST, host)
        put(K.PORT, 18448)
        put(K.TOKEN, "tok")
        put(K.SOURCE, "overhead-1")
        put(K.SECURE, pin != null)
        if (pin != null) put(K.LEGACY_PIN, pin)
        put("lens", "standard")
    }

    /** What SettingsStore.write does to the stored map. */
    private fun write(values: Map<String, Any?>, link: SiteLink): Map<String, Any?> {
        val out = values.toMutableMap()
        K.encode(link).forEach { (key, value) -> if (value == null) out.remove(key) else out[key] = value }
        return out
    }

    @Test
    fun aPairedLinkKeepsItsCredentialIdAndAPastedOneClearsIt() {
        val paired = SiteLink(
            "Rosy Lab", "fixture-site.local", 8443, pin, "t".repeat(43), "ceiling_north", secure = true,
            expiresAt = "2027-03-30T00:00:00Z", credentialId = "cred-0a1b2c3d4e5f",
        )
        val stored = write(emptyMap(), paired)
        assertEquals("cred-0a1b2c3d4e5f", stored[K.CREDENTIAL_ID])
        assertEquals(paired, K.decode(stored))
        // A later manual save writes no credential_id, so the old one does not linger beside a new token.
        val pasted = paired.copy(token = "other", credentialId = null)
        assertFalse(write(stored, pasted).containsKey(K.CREDENTIAL_ID))
    }

    @Test
    fun oldIpMigratesToManualHostAndTheWriteDropsTheOldKeys() {
        val old = legacy("192.168.1.102")
        val link = K.decode(old)!!
        assertEquals("192.168.1.102", link.manualHost)
        assertNull(link.tlsHost)
        assertEquals(pin, link.caPin)

        val stored = write(old, link)
        assertFalse("old host key must go", K.LEGACY_HOST in stored)
        assertFalse("old pin key must go", K.LEGACY_PIN in stored)
        assertEquals("192.168.1.102", stored[K.MANUAL_HOST])
        assertEquals(pin, stored[K.CA_PIN])
        assertFalse(K.TLS_HOST in stored)
        assertEquals("standard", stored["lens"])
        assertEquals(link, K.decode(stored))
    }

    @Test
    fun oldIpv6MigratesToManualHost() {
        val link = K.decode(legacy("fe80::1"))!!
        assertEquals("fe80::1", link.manualHost)
        assertNull(link.tlsHost)
    }

    @Test
    fun oldNameMigratesToTlsHost() {
        val old = legacy("perpros.local")
        val link = K.decode(old)!!
        assertEquals("perpros.local", link.tlsHost)
        assertNull(link.manualHost)
        val stored = write(old, link)
        assertEquals("perpros.local", stored[K.TLS_HOST])
        assertFalse(K.MANUAL_HOST in stored)
        assertFalse(K.LEGACY_HOST in stored)
    }

    @Test
    fun anOldKeyBesideNewKeysWinsBecauseAnOlderAppWroteLast() {
        val mixed = legacy("192.168.1.50") + mapOf(K.TLS_HOST to "perpros.local", K.CA_PIN to pin, K.ROLE to SiteLink.ROLE)
        val link = K.decode(mixed)!!
        assertEquals("192.168.1.50", link.manualHost)
        assertNull(link.tlsHost)
        val stored = write(mixed, link)
        assertFalse(K.LEGACY_HOST in stored)
        assertFalse("a stale new key must not survive the rewrite", K.TLS_HOST in stored)
    }

    @Test
    fun oldPairingWithoutAPin() {
        val link = K.decode(legacy("192.168.1.102", pin = null))!!
        assertNull(link.caPin)
        assertFalse(link.secure)
        val stored = write(legacy("192.168.1.102", pin = null) + (K.CA_PIN to pin), link)
        assertFalse("a pairing without a pin must not keep another site's pin", K.CA_PIN in stored)
    }

    @Test
    fun anOldNonLocalNameIsRejectedSoTheOperatorRePairs() {
        // D-391 1 decision (2026-10-01): a DNS name is no longer a tls_host. An old IP still migrates to manual_host.
        val old = legacy("site-pc.example.org")
        assertNull(K.decode(old))
        assertEquals("site-pc.example.org", K.rejectedHost(old))

        assertEquals("192.168.1.102", K.decode(legacy("192.168.1.102"))!!.manualHost)
        assertNull(K.rejectedHost(legacy("192.168.1.102")))
        assertNull(K.rejectedHost(legacy("perpros.local")))
        assertNull("nothing stored is not a rejected pairing", K.rejectedHost(emptyMap()))
    }

    @Test
    fun aNewFormatRecordWithANonLocalTlsHostIsRejectedToo() {
        // Written by a build before the .local rule.
        val stored = mapOf(
            K.TLS_HOST to "site-pc.example.org", K.CA_PIN to pin, K.ROLE to SiteLink.ROLE,
            K.PORT to 443, K.TOKEN to "tok", K.SOURCE to "overhead-1", K.SECURE to true,
        )
        assertNull(K.decode(stored))
        assertEquals("site-pc.example.org", K.rejectedHost(stored))
    }

    private fun stored(tlsHost: String?, manualHost: String? = null, pin: String? = this.pin): Map<String, Any?> = buildMap {
        tlsHost?.let { put(K.TLS_HOST, it) }
        manualHost?.let { put(K.MANUAL_HOST, it) }
        pin?.let { put(K.CA_PIN, it) }
        put(K.ROLE, SiteLink.ROLE)
        put(K.PORT, 443)
        put(K.TOKEN, "tok")
        put(K.SOURCE, "overhead-1")
        put(K.SECURE, true)
    }

    @Test
    fun aRejectedHostIsReportedOnlyWhenTheHostIsTheFault() {
        // Review 1: a .local host with a bad pin is broken, but not because of its host.
        val badPin = stored("perpros.local", pin = "sha256/short")
        assertNull(K.decode(badPin))
        assertNull(K.rejectedHost(badPin))
        val oldBadPin = legacy("perpros.local", pin = "sha256/short")
        assertNull(K.decode(oldBadPin))
        assertNull(K.rejectedHost(oldBadPin))
    }

    @Test
    fun aNonLocalNameWithAnIpIsSalvagedAndWithoutOneIsRejected() {
        // Decision 5: keep dialling the manual IP, drop the name, soft note; no IP left is the hard re-pair case.
        val salvage = K.read(stored("site-pc.example.org", manualHost = "192.168.1.102"))
        assertEquals("192.168.1.102", salvage.link!!.manualHost)
        assertNull(salvage.link!!.tlsHost)
        assertEquals("site-pc.example.org", salvage.droppedTlsHost)
        assertNull(salvage.rejectedHost)
        assertNull(SiteLink.validate(salvage.link!!))

        val hard = K.read(stored("site-pc.example.org"))
        assertNull(hard.link)
        assertNull(hard.droppedTlsHost)
        assertEquals("site-pc.example.org", hard.rejectedHost)
    }

    @Test
    fun aStoredTlsHostIsReadCanonical() {
        // Review 3: stored values are canonical after reading, whatever an older build wrote.
        assertEquals("perpros.local", K.decode(stored("Perpros.Local. "))!!.tlsHost)
    }

    @Test
    fun invalidOrIncompleteRecordsReadAsNothing() {
        assertNull(K.decode(emptyMap()))
        assertNull(K.decode(legacy("192.168.1.5:8443")))
        assertNull(K.decode(legacy("192.168.1.102") - K.TOKEN))
    }
}
