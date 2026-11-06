package io.github.livsbittt.rosy.cam.service

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AutoStartTest {
    @Test
    fun aPairedPhoneWithCameraPermissionReopensTheLink() {
        assertTrue(shouldAutoStart(paired = true, cameraGranted = true, running = false))
    }

    @Test
    fun nothingStartsWithoutAPairingACameraGrantOrWhileRunning() {
        assertFalse(shouldAutoStart(paired = false, cameraGranted = true, running = false))
        assertFalse(shouldAutoStart(paired = true, cameraGranted = false, running = false))
        assertFalse(shouldAutoStart(paired = true, cameraGranted = true, running = true))
    }
}
