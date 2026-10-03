package io.github.livsbittt.rosy.cam.settings

import java.time.Instant
import java.io.File
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class LinkPolicyTest {
    private val now = Instant.parse("2026-10-03T00:00:00Z")
    private fun scope() = JSONObject("""{"mode":"development","site_name":"lab","expires_at":"2026-10-03T01:00:00Z","devices":[{"device_id":"cam-1","service_type":"_rosy-overhead._tcp","tls_host":"lab.local"}]}""")

    @Test fun sharedPolicyAndPermitVectors() {
        val root = JSONObject(File(System.getProperty("rosy.linkpolicy.vectors")).readText())
        val timestamp = Instant.parse(root.getString("now"))
        val cases = root.getJSONArray("cases")
        var bound: LinkPolicy? = null
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val result = runCatching { LinkPolicy.parse(case.optJSONObject("policy"), case.optString("deployment") == "production", timestamp) }
            assertEquals(case.getString("id"), case.getJSONObject("expect").getBoolean("accepted"), result.isSuccess)
            if (case.getString("id") == "development_bound") bound = result.getOrThrow()
        }
        val permits = root.getJSONArray("permits")
        for (i in 0 until permits.length()) {
            val row = permits.getJSONObject(i)
            assertEquals(row.getString("id"), row.getBoolean("expected"), bound!!.permits(
                row.getString("device_id"), row.getString("service_type"), row.getString("tls_host"),
                row.getBoolean("authenticated"), if (row.has("now")) Instant.parse(row.getString("now")) else timestamp,
            ))
        }
    }

    @Test fun explicitAuthenticatedBindingOnly() {
        val policy = LinkPolicy.parse(scope(), now = now)
        assertTrue(policy.permits("cam-1", "_rosy-overhead._tcp", "lab.local", true, now))
        assertFalse(policy.permits("cam-1", "_rosy-overhead._tcp", "lab.local", false, now))
        assertFalse(policy.permits("cam-2", "_rosy-overhead._tcp", "lab.local", true, now))
        assertFalse(policy.permits("cam-1", "_rosy-overhead._tcp", "lab.local", true, policy.expiresAt))
    }
    @Test fun rejectsProductionExpiryDuplicateAndImplicitScope() {
        assertThrows(IllegalArgumentException::class.java) { LinkPolicy.parse(scope(), production = true, now = now) }
        assertThrows(IllegalArgumentException::class.java) { LinkPolicy.parse(scope(), now = now.plusSeconds(3600)) }
        val duplicate = scope().apply { getJSONArray("devices").put(getJSONArray("devices").getJSONObject(0)) }
        assertThrows(IllegalArgumentException::class.java) { LinkPolicy.parse(duplicate, now = now) }
        assertThrows(IllegalArgumentException::class.java) { LinkPolicy.parse(JSONObject("""{"mode":"paired","devices":[]}"""), now = now) }
        assertEquals("paired", LinkPolicy.parse(null, now = now).mode)
    }
}
