package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test
import okhttp3.tls.HeldCertificate
import java.time.Instant

class ProfileTest {
    private val ca = HeldCertificate.Builder().certificateAuthority(1).build()
    private fun json(host: String = "robot-a.local", expiry: String = "2099-01-01T00:00:00Z") = """
        {"policy":{"mode":"development","site_name":"test","expires_at":"$expiry","devices":[
        {"device_id":"rosy_01","service_type":"_rosy._tcp","tls_host":"robot-a.local"}]},
        "ca_pem":${org.json.JSONObject.quote(ca.certificatePem())},"robots":[
        {"robot_id":"rosy_01","tls_host":"$host","port":8080,"credential":"private-token-value"}]}
    """.trimIndent()
    @Test fun scopedImport() {
        val profile = PilotProfile.parse(json())
        assertEquals("robot-a.local", profile.robots.single().host)
        assertFalse(profile.toString().contains("private-token"))
    }
    @Test fun refusesIpOrForeignBinding() { for (host in listOf("192.0.2.4", "foreign.local")) {
        assertThrows(IllegalArgumentException::class.java) { PilotProfile.parse(json(host)) }
    } }
    @Test fun refusesExpiredAndLeafTrust() {
        assertThrows(Exception::class.java) { PilotProfile.parse(json(expiry = "2000-01-01T00:00:00Z")) }
        val leaf = HeldCertificate.Builder().build()
        assertThrows(Exception::class.java) { PilotProfile.parse(json().replace(org.json.JSONObject.quote(ca.certificatePem()), org.json.JSONObject.quote(leaf.certificatePem()))) }
    }
    @Test fun refusesDuplicateRobots() {
        val data = org.json.JSONObject(json()); val rows = data.getJSONArray("robots")
        rows.put(rows.getJSONObject(0))
        assertThrows(Exception::class.java) { PilotProfile.parse(data.toString()) }
    }
    @Test fun noOriginOrMissingCapabilityIsRejected() {
        val guard = ProxyGuard("127.0.0.1:1234", "private-capability")
        assertTrue(guard.permits(mapOf("host" to "127.0.0.1:1234", "cookie" to "rosy-shell=private-capability")))
        assertFalse(guard.permits(mapOf("host" to "attacker.local", "cookie" to "rosy-shell=private-capability")))
        assertFalse(guard.permits(mapOf("host" to "127.0.0.1:1234", "cookie" to "rosy-shell=private-capability", "origin" to "https://attacker.local")))
        assertFalse(guard.permits(mapOf("host" to "127.0.0.1:1234")))
    }
    @Test fun generationAndConflictingAdvertisements() {
        val state = CandidateStore()
        val first = state.found("one")!!
        state.lost("one")
        state.resolved("one", first, Candidate("robot-a.local", 8080, listOf("192.0.2.1")))
        assertNull(state.addresses("robot-a.local", 8080))
        val again = state.found("one")!!
        state.resolved("one", first, Candidate("robot-a.local", 8080, listOf("192.0.2.99")))
        assertNull(state.addresses("robot-a.local", 8080))
        state.resolved("one", again, Candidate("robot-a.local", 8080, listOf("192.0.2.1")))
        val second = state.found("two")!!
        state.resolved("two", second, Candidate("robot-a.local", 8080, listOf("192.0.2.2")))
        assertThrows(IllegalStateException::class.java) { state.addresses("robot-a.local", 8080) }
    }
    @Test fun sharedRobotTxtVectors() {
        val cases = org.json.JSONObject(java.io.File(System.getProperty("rosy.discovery.vectors")).readText()).getJSONArray("cases")
        var checked = 0
        for (i in 0 until cases.length()) {
            val row = cases.getJSONObject(i)
            if (row.getString("service_type").trimEnd('.') != "_rosy._tcp") continue
            val items = row.getJSONArray("txt").let { a -> List(a.length()) { a.getString(it) } }
            if (items.map { it.substringBefore('=') }.distinct().size != items.size) continue
            val attributes = items.associate { it.substringBefore('=') to it.substringAfter('=').toByteArray() }
            val result = io.github.livsbittt.rosy.cam.settings.RobotCoreServiceRecord.rejection(
                row.getString("service_type"), row.optString("address").takeUnless { row.isNull("address") }, row.getInt("port"), attributes,
                row.optString("host").takeUnless { row.isNull("host") })
            val expect = row.getJSONObject("expect")
            assertEquals(row.getString("id"), if (expect.getBoolean("accepted")) null else expect.getString("reason"), result)
            checked++
        }
        assertTrue(checked >= 10)
    }
}
