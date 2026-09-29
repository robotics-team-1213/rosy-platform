package io.github.livsbittt.rosy.overhead.ui

import io.github.livsbittt.rosy.overhead.link.ServerMessage
import org.junit.Assert.assertEquals
import org.junit.Test

class CornerGuideTest {
    private fun status(seen: List<Int>, needed: Int = 4, robots: List<String> = emptyList()) =
        ServerMessage.Status(seen, needed, robots, rxFps = 3.0, dropped = 0)

    @Test
    fun partialNamesSeenIdsInOrderAndFillsDotsFirst() {
        val g = CornerGuide.from(status(listOf(33, 30), robots = listOf("rosy_02", "rosy_01")))
        assertEquals(CornerGuide.Progress.PARTIAL, g.progress)
        assertEquals(2, g.seenCount)
        assertEquals("30, 33", g.seenIds)
        assertEquals(listOf(true, true, false, false), g.dots)
        assertEquals("rosy_01, rosy_02", g.robotIds)
    }

    @Test
    fun noneAndComplete() {
        assertEquals(CornerGuide.Progress.NONE, CornerGuide.from(status(emptyList())).progress)
        assertEquals(listOf(false, false, false, false), CornerGuide.from(status(emptyList())).dots)
        val done = CornerGuide.from(status(listOf(30, 31, 32, 33)))
        assertEquals(CornerGuide.Progress.COMPLETE, done.progress)
        assertEquals(listOf(true, true, true, true), done.dots)
    }

    @Test
    fun duplicateIdsCountOnce() {
        val g = CornerGuide.from(status(listOf(30, 30, 31)))
        assertEquals(2, g.seenCount)
        assertEquals(CornerGuide.Progress.PARTIAL, g.progress)
    }

    @Test
    fun matchesTheSharedStatusVector() {
        // vectors.json status_example: corners_seen [30, 31, 33], corners_needed 4, robots_seen [rosy_01].
        val g = CornerGuide.from(status(listOf(30, 31, 33), 4, listOf("rosy_01")))
        assertEquals("30, 31, 33", g.seenIds)
        assertEquals(listOf(true, true, true, false), g.dots)
    }

    @Test
    fun placeholderEmptyStatusIsNotAMarkerReport() {
        // `overhead receive` always sends empty lists; that must not render as "0/4 seen".
        assertEquals(false, CornerGuide.reportsMarkers(status(emptyList())))
        assertEquals(true, CornerGuide.reportsMarkers(status(listOf(30))))
        assertEquals(true, CornerGuide.reportsMarkers(status(emptyList(), robots = listOf("rosy_01"))))
    }
}
