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
    fun invalidOrIncompleteRecordsReadAsNothing() {
        assertNull(K.decode(emptyMap()))
        assertNull(K.decode(legacy("192.168.1.5:8443")))
        assertNull(K.decode(legacy("192.168.1.102") - K.TOKEN))
    }
}
