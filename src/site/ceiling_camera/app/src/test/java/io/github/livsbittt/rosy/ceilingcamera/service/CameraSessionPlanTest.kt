package io.github.livsbittt.rosy.overhead.service

import io.github.livsbittt.rosy.overhead.settings.PairingUri
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CameraSessionPlanTest {
    @Test
    fun missingPairingStillStartsCameraPreviewWithoutSendingFrames() {
        val plan = CameraSessionPlan.from(null)

        assertTrue(plan.startCamera)
        assertFalse(plan.sendFrames)
    }

    @Test
    fun pairedSessionStartsCameraAndSendsFrames() {
        val pairing = PairingUri("localhost", 8095, "test-token", "overhead-1", false)
        val plan = CameraSessionPlan.from(pairing)

        assertTrue(plan.startCamera)
        assertTrue(plan.sendFrames)
    }
}
