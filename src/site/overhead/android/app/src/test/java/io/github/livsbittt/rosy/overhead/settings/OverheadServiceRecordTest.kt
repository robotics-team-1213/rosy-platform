package io.github.livsbittt.rosy.overhead.settings

import java.nio.charset.StandardCharsets.UTF_8
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotNull
import org.junit.Test

class OverheadServiceRecordTest {
    @Test
    fun acceptsOnlyTlsOverheadReceiverAdvertisements() {
        val record = OverheadServiceRecord.parse(
            serviceType = "_rosy-overhead._tcp.",
            serviceName = "ROSY Overhead site-a",
            tlsHost = "site-a.local",
            port = 8443,
            attributes = attributes(),
        )

        assertNotNull(record)
        assertEquals("site-a.local", record?.tlsHost)
        assertEquals(8443, record?.port)
        assertEquals("ROSY Overhead site-a", record?.serviceName)
    }

    @Test
    fun rejectsFleetIngestAndCleartextAdvertisements() {
        assertNull(OverheadServiceRecord.parse(
            "_rosy-fleet._tcp.", "Fleet", "site-a.local", 8443, attributes(),
        ))
        assertNull(OverheadServiceRecord.parse(
            "_rosy-overhead._tcp.", "Camera", "site-a.local", 8095,
            attributes().toMutableMap().also { it["tls"] = "optional".bytes() },
        ))
    }

    @Test
    fun identifiesRobotCoreAsASeparateDiscoveredService() {
        val record = RobotCoreServiceRecord.parse(
            serviceType = "_rosy._tcp.",
            serviceName = "rosy-pinky-01",
            resolvedHost = "rosy-pinky-01.local",
            port = 8080,
            attributes = mapOf(
                "product" to "rosy".bytes(),
                "role" to "robot".bytes(),
                "proto" to "core-v1".bytes(),
                "tls" to "none".bytes(),
            ),
        )

        assertNotNull(record)
        assertEquals("rosy-pinky-01.local", record?.host)
        assertEquals(8080, record?.port)
    }

    @Test
    fun acceptsAndroidResolvedServiceTypeWithLeadingDot() {
        val record = RobotCoreServiceRecord.parse(
            serviceType = "._rosy._tcp",
            serviceName = "ROSY rosy-pinky-pagt",
            resolvedHost = "192.168.1.202",
            port = 8080,
            attributes = mapOf(
                "product" to "rosy".bytes(),
                "role" to "robot".bytes(),
                "proto" to "core-v1".bytes(),
                "tls" to "none".bytes(),
            ),
        )

        assertNotNull(record)
    }

    private fun attributes() = mapOf(
        "product" to "rosy".bytes(),
        "role" to "overhead-camera".bytes(),
        "proto" to "rosy-overhead/1".bytes(),
        "tls" to "required".bytes(),
        "tls_host" to "site-a.local".bytes(),
    )

    private fun String.bytes() = toByteArray(UTF_8)
}
