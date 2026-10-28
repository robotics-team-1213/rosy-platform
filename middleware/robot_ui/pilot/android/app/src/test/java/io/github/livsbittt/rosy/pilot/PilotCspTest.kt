package io.github.livsbittt.rosy.pilot

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PilotCspTest {
    private val core = "default-src 'self'; connect-src 'self' ws: wss: https://media.site.local:8889; img-src 'self' data: blob:"

    @Test fun coreMediaOriginReachesConnectSrcOnly() {
        val origin = PilotCsp.mediaOrigin(core)
        assertEquals("https://media.site.local:8889", origin)
        val policy = PilotCsp.header(origin)
        assertTrue(policy.contains("connect-src 'self' https://media.site.local:8889;"))
        assertTrue(policy.contains("default-src 'self';"))
    }

    @Test fun withoutSiteMediaThePolicyStaysSelfOnly() {
        assertNull(PilotCsp.mediaOrigin("default-src 'self'; connect-src 'self' ws: wss:; img-src 'self'"))
        assertNull(PilotCsp.mediaOrigin(null))
        assertTrue(PilotCsp.header(null).contains("connect-src 'self'; worker-src"))
    }

    @Test fun onlyAPlainHttpsOriginIsAccepted() {
        for (bad in listOf("http://media.local", "https://user@media.local", "https://media.local/path",
                "https://media.local?x=1", "https://media.local#f", "https://me'dia.local", "https://*.local")) {
            assertNull(bad, PilotCsp.mediaOrigin("connect-src 'self' $bad"))
        }
        assertEquals("https://media.local", PilotCsp.mediaOrigin("connect-src 'self' https://media.local/"))
    }
}
