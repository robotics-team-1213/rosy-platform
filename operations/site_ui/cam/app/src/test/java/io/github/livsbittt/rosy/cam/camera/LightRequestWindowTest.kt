package io.github.livsbittt.rosy.cam.camera

import org.junit.Assert.*
import org.junit.Test

class LightRequestWindowTest {
    @Test fun idleNeedsExplicitRequest() {
        val window = LightRequestWindow()
        assertFalse(window.active(0))
        assertFalse(window.active(100000))
        assertFalse(LightingStatus().requested)
    }
    @Test fun expiresWithoutRearming() {
        val window = LightRequestWindow()
        window.start(100)
        assertTrue(window.active(30099))
        assertFalse(window.active(30100))
        assertFalse(window.active(100000))
        window.start(100000)
        assertTrue(window.active(100001))
    }
    @Test fun repeatedRequestCannotExtend() {
        val window = LightRequestWindow()
        window.start(100)
        window.start(20000)
        assertFalse(window.active(30100))
    }
    @Test fun cancelAndClockReversalEndRequest() {
        val window = LightRequestWindow()
        window.start(100)
        window.cancel()
        assertFalse(window.active(101))
        window.start(200)
        assertFalse(window.active(199))
        assertFalse(window.active(201))
    }
}
