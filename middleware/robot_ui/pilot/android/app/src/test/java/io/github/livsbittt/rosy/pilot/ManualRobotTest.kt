package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test

class ManualRobotTest {
    @Test fun explicitLanAddressKeepsTransportAndNeedsAuthenticatedPairing() {
        val http = ManualRobot.parse("http://192.168.10.42:8080")
        assertEquals("192.168.10.42", http.host)
        assertEquals(8080, http.port)
        assertFalse(http.secure)
        assertEquals("", http.robotId)
        assertThrows(IllegalArgumentException::class.java) { ManualRobot.parse("https://192.168.10.42:8080") }
        val store = CandidateStore().apply { manual(http) }
        assertEquals(listOf(http), store.records())
        assertThrows(IllegalArgumentException::class.java) {
            LobbyPairing.connect(http, LobbyOffer("paired", "rosy_42"), store)
        }
        store.clear()
        assertFalse(store.matches(http, "rosy_42"))
    }

    @Test fun manualInputRejectsNonLanTargetsAndEmbeddedCredentialsOrRoutes() {
        for (value in listOf("", "192.168.10.42:8080", "http://127.0.0.1:8080", "http://8.8.8.8",
            "http://robot.local:8080", "http://user:pass@192.168.10.42:8080",
            "http://192.168.10.42:8080/api/v1", "http://192.168.10.42:8080/?token=x",
            "http://192.168.10.42:8080/#x", "http://192.168.10.42:0")) {
            assertThrows(value, IllegalArgumentException::class.java) { ManualRobot.parse(value) }
        }
    }

    @Test fun discoveryConflictStillRevokesManuallySelectedTarget() {
        val manual = ManualRobot.parse("http://192.168.10.42:8080")
        val store = CandidateStore().apply { manual(manual) }
        assertTrue(store.matches(manual, "rosy_42"))
        store.resolved("robot", store.found("robot")!!, manual.copy(secure = true))
        assertFalse(store.matches(manual, "rosy_42"))
    }

    @Test fun manualEntrySharesTheExistingCandidateBudget() {
        val row = ManualRobot.parse("http://192.168.10.42:8080")
        val full = CandidateStore()
        repeat(64) { assertNotNull(full.found("robot-$it")) }
        assertFalse(full.manual(row))
        val manual = CandidateStore()
        assertTrue(manual.manual(row))
        repeat(63) { assertNotNull(manual.found("robot-$it")) }
        assertNull(manual.found("one-too-many"))
    }
}
