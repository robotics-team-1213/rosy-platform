package io.github.livsbittt.rosy.overhead.settings

import java.io.File
import java.nio.charset.StandardCharsets.UTF_8
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * D-358 5.1: the Android discovery records follow test/fixtures/protocol/discovery-txt.v1.json,
 * the same vectors the Python parsers read.
 */
class DiscoveryVectorsTest {
    private val root: JSONObject by lazy {
        val path = System.getProperty("rosy.discovery.vectors")
            ?: error("system property rosy.discovery.vectors is not set (see app/build.gradle.kts)")
        JSONObject(File(path).readText(UTF_8))
    }

    /**
     * Current robot-record behaviour that differs from the vectors. The phone lists robots for
     * information only and does not yet check address, host, AP mode or legacy adverts; closing
     * these is an app behaviour change for a later round. Each entry must keep differing, so a
     * fix forces its removal here.
     */
    private val knownRobotDivergence = setOf(
        "robot_legacy_without_common_keys",
        "robot_legacy_ap_mode",
        "robot_ap_mode",
        "robot_bad_address_link_local",
        "robot_bad_address_public",
        "robot_bad_address_loopback",
        "robot_bad_address_ipv6",
        "robot_bad_host",
    )

    @Test
    fun androidRecordsFollowTheSharedVectors() {
        val cases = root.getJSONArray("cases")
        var checked = 0
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val id = case.getString("id")
            val type = case.getString("service_type")
            val items = case.getJSONArray("txt").let { a -> List(a.length()) { a.getString(it) } }
            // Android NSD hands over a Map, so a duplicate key cannot reach these parsers.
            if (items.map { it.substringBefore('=') }.toSet().size != items.size) continue
            val attributes = items.associate { it.substringBefore('=') to it.substringAfter('=').toByteArray(UTF_8) }
            val port = case.getInt("port")
            val actual = when (normalizeServiceType(type)) {
                "_rosy-overhead._tcp" ->
                    OverheadServiceRecord.rejection(type, case.optStringOrNull("host"), port, attributes)
                "_rosy._tcp" ->
                    RobotCoreServiceRecord.rejection(type, case.optStringOrNull("address"), port, attributes)
                // The app has no Fleet parser; the frame target must refuse every other type.
                else -> if (case.getJSONObject("expect").optString("reason") == "wrong_type") {
                    OverheadServiceRecord.rejection(type, case.optStringOrNull("host"), port, attributes)
                } else continue
            }
            val expect = case.getJSONObject("expect")
            val expected = if (expect.getBoolean("accepted")) null else expect.getString("reason")
            if (id in knownRobotDivergence) {
                assertNotEquals("$id is fixed now; remove it from knownRobotDivergence", expected, actual)
            } else {
                assertEquals(id, expected, actual)
            }
            checked++
        }
        assertTrue("too few vectors reached the Android parsers: $checked", checked >= 20)
    }

    private fun JSONObject.optStringOrNull(key: String): String? = if (isNull(key)) null else getString(key)
}
