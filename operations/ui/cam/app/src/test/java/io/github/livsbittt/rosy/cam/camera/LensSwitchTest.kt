package io.github.livsbittt.rosy.cam.camera

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LensSwitchTest {
    private val bound = mutableListOf<String?>()

    private fun binder(failing: Set<String?>): (String?) -> Unit = { id ->
        bound += id
        if (id in failing) throw IllegalArgumentException("no camera $id")
    }

    @Test
    fun successfulSwitchBindsOnlyTheNewCamera() {
        assertEquals(LensSwitch.Outcome.Switched, LensSwitch.run("0", "2", binder(emptySet())))
        assertEquals(listOf<String?>("2"), bound)
    }

    @Test
    fun failedSwitchRebindsThePreviousCameraAndKeepsStreaming() {
        val outcome = LensSwitch.run("0", "2", binder(setOf("2")))
        assertTrue(outcome is LensSwitch.Outcome.RolledBack)
        assertEquals("no camera 2", (outcome as LensSwitch.Outcome.RolledBack).error.message)
        assertEquals(listOf<String?>("2", "0"), bound)
    }

    @Test
    fun failureOfBothCamerasIsFatal() {
        val outcome = LensSwitch.run("0", "2", binder(setOf("0", "2")))
        assertTrue(outcome is LensSwitch.Outcome.Failed)
        assertEquals("no camera 0", (outcome as LensSwitch.Outcome.Failed).error.message)
    }
}
