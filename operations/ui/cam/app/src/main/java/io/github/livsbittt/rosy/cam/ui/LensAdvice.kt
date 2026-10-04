package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.camera.LensChoice
import io.github.livsbittt.rosy.cam.camera.LensPick

/**
 * When to suggest the ultra-wide in the install guide. The phone only hears the receiver's corner
 * report, so "field clipped" means: markers are being reported but not all needed corners are seen.
 * Only a suggestion: the lens never changes without the operator (user decision 2026-09-30). Pure JVM.
 */
object LensAdvice {
    fun suggestWide(lens: LensPick?, wideAvailable: Boolean, guide: CornerGuide?, markersReported: Boolean): Boolean =
        lens?.kind == LensChoice.STANDARD &&
            wideAvailable &&
            markersReported &&
            guide != null &&
            guide.needed > 0 &&
            guide.progress != CornerGuide.Progress.COMPLETE
}
