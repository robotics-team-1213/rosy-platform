package io.github.livsbittt.rosy.cam.service

import org.junit.Assert.assertEquals
import org.junit.Test

class CaptureGateTest {
    @Test
    fun unpairedPreviewDoesNotSend() {
        assertEquals(CaptureGate(cameraOn = true, sendFrames = false), CaptureGate.decide(false, null, true, false))
    }

    @Test
    fun aRosyRequestTurnsTheSensorAndTheUplinkOn() {
        assertEquals(CaptureGate(cameraOn = true, sendFrames = true), CaptureGate.decide(true, true, false, false))
    }

    @Test
    fun standbyKeepsALocalPreviewAndSendsNothing() {
        assertEquals(CaptureGate(cameraOn = true, sendFrames = false), CaptureGate.decide(true, false, true, false))
        assertEquals(CaptureGate(cameraOn = false, sendFrames = false), CaptureGate.decide(true, false, false, false))
    }

    @Test
    fun anOlderVisionKeepsSendingOnlyAfterTheGrace() {
        assertEquals(CaptureGate(cameraOn = false, sendFrames = false), CaptureGate.decide(true, null, false, false))
        assertEquals(CaptureGate(cameraOn = true, sendFrames = false), CaptureGate.decide(true, null, true, false))
        assertEquals(CaptureGate(cameraOn = true, sendFrames = true), CaptureGate.decide(true, null, false, true))
    }

    @Test
    fun heatStopsTheSensorEvenWhenARosyIsWatching() {
        assertEquals(
            CaptureGate(cameraOn = false, sendFrames = false),
            CaptureGate.decide(true, true, true, true, thermalPause = true),
        )
        assertEquals(
            CaptureGate(cameraOn = false, sendFrames = false),
            CaptureGate.decide(false, null, true, false, thermalPause = true),
        )
    }
}
