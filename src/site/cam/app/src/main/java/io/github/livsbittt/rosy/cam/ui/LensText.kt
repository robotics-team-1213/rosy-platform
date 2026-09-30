package io.github.livsbittt.rosy.cam.ui

import android.content.res.Resources
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.camera.LensChoice
import io.github.livsbittt.rosy.cam.camera.LensPick
import java.util.Locale

/** Korean lens text shared by the stream screen and the foreground notification. */
object LensText {
    /** "렌즈: 초광각 2.2 mm · 화각 104°"; null when the lens reports no focal length. */
    fun line(res: Resources, pick: LensPick): String? {
        val focal = pick.camera.focalMm ?: return null
        val hfov = pick.camera.hfovDeg?.let { String.format(Locale.ROOT, "%.0f", it) } ?: "?"
        val mm = String.format(Locale.ROOT, "%.1f", focal)
        val text = res.getString(if (pick.kind == LensChoice.WIDE) R.string.lens_wide else R.string.lens_standard, mm, hfov)
        return if (pick.fellBack) text + "\n" + res.getString(R.string.lens_no_wide) else text
    }
}
