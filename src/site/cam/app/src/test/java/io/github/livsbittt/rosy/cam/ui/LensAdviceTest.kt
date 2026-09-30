package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.camera.LensCandidate
import io.github.livsbittt.rosy.cam.camera.LensChoice
import io.github.livsbittt.rosy.cam.camera.LensPick
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LensAdviceTest {
    private val main = LensCandidate("0", listOf(5.4f), 7.2576f, 5.4432f, logical = false)
    private val ultraWide = LensCandidate("2", listOf(2.2f), 5.6448f, 4.2336f, logical = false)
    private val standard = LensPick(main, LensChoice.STANDARD, fellBack = false)
    private val wide = LensPick(ultraWide, LensChoice.WIDE, fellBack = false)
    private val partial = CornerGuide(seen = listOf(30, 31), needed = 4, robots = emptyList())
    private val none = CornerGuide(seen = emptyList(), needed = 4, robots = listOf("rosy_01"))
    private val complete = CornerGuide(seen = listOf(30, 31, 32, 33), needed = 4, robots = emptyList())

    @Test
    fun suggestsWideWhenStandardMissesCorners() {
        assertTrue(LensAdvice.suggestWide(standard, wideAvailable = true, guide = partial, markersReported = true))
        assertTrue(LensAdvice.suggestWide(standard, wideAvailable = true, guide = none, markersReported = true))
    }

    @Test
    fun staysQuietWhenAllCornersAreSeen() {
        assertFalse(LensAdvice.suggestWide(standard, wideAvailable = true, guide = complete, markersReported = true))
    }

    @Test
    fun staysQuietWithoutAMarkerReport() {
        // `rosy-vision receive` sends empty placeholders: that is not "corners missing".
        assertFalse(LensAdvice.suggestWide(standard, wideAvailable = true, guide = none, markersReported = false))
        assertFalse(LensAdvice.suggestWide(standard, wideAvailable = true, guide = null, markersReported = true))
    }

    @Test
    fun staysQuietWhenAlreadyWideOrNoWideExists() {
        assertFalse(LensAdvice.suggestWide(wide, wideAvailable = true, guide = partial, markersReported = true))
        assertFalse(LensAdvice.suggestWide(standard, wideAvailable = false, guide = partial, markersReported = true))
        val fellBack = LensPick(main, LensChoice.STANDARD, fellBack = true)
        assertFalse(LensAdvice.suggestWide(fellBack, wideAvailable = false, guide = partial, markersReported = true))
        assertFalse(LensAdvice.suggestWide(null, wideAvailable = true, guide = partial, markersReported = true))
    }
}
