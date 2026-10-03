package io.github.livsbittt.rosy.pilot

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

class PilotColorsTest {
    @Test fun nativeRolesUseTheSameCanonicalDarkPaletteAsBundledScreens() {
        val css = File(System.getProperty("rosy.pilot.assets"), "common/tokens.css").readText()
        val dark = Regex(""":root,\s*\[data-theme="dark"\]\s*\{([^}]+)\}""").find(css)!!.groupValues[1]
        val roles = mapOf("ground" to PilotColors.background, "ink" to PilotColors.foreground,
            "ink-quiet" to PilotColors.muted, "brand-rose" to PilotColors.rose,
            "ground-card" to PilotColors.card, "ground-card-2" to PilotColors.pressed,
            "ground-soft" to PilotColors.disabled)
        for ((token, actual) in roles) {
            val expected = Regex("--${Regex.escape(token)}:\\s*#([a-fA-F0-9]{6});").find(dark)!!.groupValues[1].toLong(16).or(0xFF000000).toInt()
            assertEquals("Native --$token drifted from bundled canonical CSS", expected, actual)
        }
    }
}
