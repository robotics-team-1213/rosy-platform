package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.link.ServerMessage

/**
 * Installation guidance from the adapter's `status`: how many corner markers the camera sees
 * and which robots. The protocol does not say which corner ids are expected, so only the seen
 * ids can be named. Pure JVM.
 */
data class CornerGuide(val seen: List<Int>, val needed: Int, val robots: List<String>) {
    enum class Progress { NONE, PARTIAL, COMPLETE }

    val seenCount: Int get() = seen.size

    val progress: Progress
        get() = when {
            needed > 0 && seenCount >= needed -> Progress.COMPLETE
            seenCount == 0 -> Progress.NONE
            else -> Progress.PARTIAL
        }

    /** One entry per needed corner, filled ones first; drawn as dots next to the count text. */
    val dots: List<Boolean> get() = List(needed.coerceIn(0, MAX_DOTS)) { it < seenCount }

    val seenIds: String get() = seen.joinToString(", ")
    val robotIds: String get() = robots.joinToString(", ")

    companion object {
        private const val MAX_DOTS = 8

        /**
         * True once the receiver reports any marker. `rosy-vision receive` (and Vision before it
         * sees a frame) sends empty placeholder lists, which must not read as "0/4 seen".
         */
        fun reportsMarkers(status: ServerMessage.Status): Boolean =
            status.cornersSeen.isNotEmpty() || status.robotsSeen.isNotEmpty()

        fun from(status: ServerMessage.Status): CornerGuide = CornerGuide(
            seen = status.cornersSeen.distinct().sorted(),
            needed = status.cornersNeeded.coerceAtLeast(0),
            robots = status.robotsSeen.distinct().sorted(),
        )
    }
}
