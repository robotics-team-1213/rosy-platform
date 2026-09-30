package io.github.livsbittt.rosy.cam.camera

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LensSelectorTest {
    // Galaxy S21, Android 15, `dumpsys media.camera` 2026-09-30.
    private val main = LensCandidate("0", listOf(5.4f), 7.2576f, 5.4432f, logical = false)
    private val ultraWide = LensCandidate("2", listOf(2.2f), 5.6448f, 4.2336f, logical = false)
    private val logicalMain = LensCandidate("3", listOf(5.4f), 7.2576f, 5.4432f, logical = true)
    private val s21 = listOf(main, ultraWide, logicalMain)

    @Test
    fun hfovOfS21LensesFollowsSensorLongEdgeAndFocalLength() {
        assertEquals(67.8, main.hfovDeg!!, 0.1)
        assertEquals(104.1, ultraWide.hfovDeg!!, 0.1)
    }

    @Test
    fun wideOnS21PicksThePhysicalUltraWide() {
        val pick = LensSelector.pick(s21, LensChoice.WIDE)!!
        assertEquals("2", pick.camera.id)
        assertEquals(LensChoice.WIDE, pick.kind)
        assertFalse(pick.fellBack)
        assertTrue(LensSelector.hasWide(s21))
    }

    @Test
    fun standardIsTheFirstBackCamera() {
        val pick = LensSelector.pick(s21, LensChoice.STANDARD)!!
        assertEquals("0", pick.camera.id)
        assertEquals(LensChoice.STANDARD, pick.kind)
        assertFalse(pick.fellBack)
    }

    @Test
    fun wideFallsBackToStandardWhenNothingIsWider() {
        val phone = listOf(main, logicalMain, LensCandidate("4", listOf(7.0f), 7.2576f, 5.4432f, logical = false))
        val pick = LensSelector.pick(phone, LensChoice.WIDE)!!
        assertEquals("0", pick.camera.id)
        assertEquals(LensChoice.STANDARD, pick.kind)
        assertTrue(pick.fellBack)
        assertFalse(LensSelector.hasWide(phone))
    }

    @Test
    fun slightlyWiderLensDoesNotCountAsWide() {
        val nearTwin = LensCandidate("5", listOf(5.2f), 7.2576f, 5.4432f, logical = false)
        assertTrue(nearTwin.hfovDeg!! - main.hfovDeg!! < LensSelector.MIN_WIDER_DEG)
        assertTrue(LensSelector.pick(listOf(main, nearTwin), LensChoice.WIDE)!!.fellBack)
    }

    @Test
    fun physicalCameraIsPreferredOverAWiderLogicalOne() {
        val logicalWide = LensCandidate("6", listOf(1.8f), 5.6448f, 4.2336f, logical = true)
        val pick = LensSelector.pick(listOf(main, logicalWide, ultraWide), LensChoice.WIDE)!!
        assertEquals("2", pick.camera.id)
    }

    @Test
    fun logicalWideIsUsedWhenItIsTheOnlyWiderCamera() {
        val logicalWide = LensCandidate("6", listOf(2.2f), 5.6448f, 4.2336f, logical = true)
        assertEquals("6", LensSelector.pick(listOf(main, logicalWide), LensChoice.WIDE)!!.camera.id)
    }

    @Test
    fun widestOfSeveralWideCamerasWins() {
        val lessWide = LensCandidate("7", listOf(3.5f), 5.6448f, 4.2336f, logical = false)
        assertEquals("2", LensSelector.pick(listOf(main, lessWide, ultraWide), LensChoice.WIDE)!!.camera.id)
    }

    @Test
    fun missingSensorSizeFallsBackToFocalLength() {
        val noSize = LensCandidate("8", listOf(2.2f), null, null, logical = false)
        assertNull(noSize.hfovDeg)
        assertEquals("8", LensSelector.pick(listOf(main, noSize), LensChoice.WIDE)!!.camera.id)
    }

    @Test
    fun shortestOfSeveralFocalLengthsIsTheEffectiveOne() {
        val zoomLens = LensCandidate("9", listOf(6.0f, 2.4f), 7.2576f, 5.4432f, logical = false)
        assertEquals(2.4f, zoomLens.focalMm!!, 0f)
    }

    @Test
    fun noBackCameraPicksNothing() {
        assertNull(LensSelector.pick(emptyList(), LensChoice.WIDE))
        assertFalse(LensSelector.hasWide(emptyList()))
    }

    @Test
    fun defaultIsStandardAndAppliesOnlyWhenNothingIsSaved() {
        assertEquals(LensChoice.STANDARD, LensChoice.DEFAULT)
        assertEquals(LensChoice.STANDARD, LensChoice.orDefault(null))
        assertEquals(LensChoice.WIDE, LensChoice.orDefault(LensChoice.WIDE))
        assertEquals(LensChoice.STANDARD, LensChoice.orDefault(LensChoice.fromWire("unknown")))
        // Default on S21: the main camera, even though an ultra-wide exists.
        assertEquals("0", LensSelector.pick(s21, LensChoice.orDefault(null))!!.camera.id)
    }

    @Test
    fun choiceRoundTripsThroughItsWireName() {
        for (choice in LensChoice.entries) assertEquals(choice, LensChoice.fromWire(choice.wire))
        assertNull(LensChoice.fromWire("tele"))
        assertNull(LensChoice.fromWire(null))
    }
}
