package io.github.livsbittt.rosy.cam.settings

import java.time.Instant
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class DevelopmentBootstrapTest {
    private val now = Instant.parse("2026-10-03T00:00:00Z")
    private val ca = HeldCertificate.Builder().certificateAuthority(1).commonName("Disposable test CA").build()
    private fun envelope(): JSONObject {
        val policy = JSONObject("""{"mode":"development","site_name":"lab","expires_at":"2026-10-03T01:00:00Z","devices":[{"device_id":"cam-1","service_type":"_rosy-overhead._tcp","tls_host":"lab.local"}]}""")
        val record = JSONObject().put("site_name", "lab").put("tls_host", "lab.local").put("port", 9443)
            .put("ca_pem", ca.certificatePem()).put("role", "overhead-camera").put("credential_id", "test-only")
            .put("expires_at", "2026-10-03T01:00:00Z").put("credential", "test-only-token")
        return JSONObject().put("policy", policy).put("site_link", record).put("source", "cam-1")
    }
    @Test fun importsTrustAndTokenWithoutDisablingTls() {
        val bootstrap = DevelopmentBootstrap.parse(envelope().toString(), now)
        assertTrue(bootstrap.link.secure)
        assertEquals(io.github.livsbittt.rosy.cam.link.certPin(ca.certificate.encoded), bootstrap.link.caPin)
        assertEquals("test-only-token", bootstrap.link.token)
        assertEquals("lab.local", bootstrap.link.dialHost)
        assertNull(bootstrap.link.manualHost)
    }
    @Test fun rejectsWrongSiteSourceLeafAndExpiredScope() {
        val wrongSite = envelope().apply { getJSONObject("site_link").put("site_name", "another") }
        assertThrows(IllegalArgumentException::class.java) { DevelopmentBootstrap.parse(wrongSite.toString(), now) }
        assertThrows(IllegalArgumentException::class.java) { DevelopmentBootstrap.parse(envelope().put("source", "other").toString(), now) }
        assertThrows(IllegalArgumentException::class.java) { DevelopmentBootstrap.parse(envelope().toString(), now.plusSeconds(3600)) }
        val leaf = HeldCertificate.Builder().commonName("lab.local").build()
        val badCa = envelope().apply { getJSONObject("site_link").put("ca_pem", leaf.certificatePem()) }
        assertThrows(IllegalStateException::class.java) { DevelopmentBootstrap.parse(badCa.toString(), now) }
    }
}
