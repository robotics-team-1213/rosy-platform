package io.github.livsbittt.rosy.cam.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/** The Material roles the app relies on map to the intended Rosy colours. */
class RosyColorSchemeTest {
    private val scheme = RosyColorScheme

    @Test
    fun primaryCommandIsTheBrightestNeutral() {
        assertEquals(RosyColors.Paper, scheme.primary)
        assertEquals(RosyColors.Ground, scheme.onPrimary)
    }

    @Test
    fun pageIsTheGroundWithPaperInk() {
        assertEquals(RosyColors.Ground, scheme.background)
        assertEquals(RosyColors.Paper, scheme.onBackground)
        assertEquals(RosyColors.Paper, scheme.onSurface)
        assertEquals(RosyColors.Muted, scheme.onSurfaceVariant)
    }

    @Test
    fun errorIsTheCritFillWithPaperInk() {
        assertEquals(RosyColors.StatusCrit, scheme.error)
        assertEquals(RosyColors.Paper, scheme.onError)
    }

    @Test
    fun brandRoseIsNotAnyMaterialRole() {
        val roles = listOf(
            scheme.primary, scheme.secondary, scheme.tertiary, scheme.background, scheme.surface,
            scheme.surfaceVariant, scheme.error, scheme.outline, scheme.outlineVariant,
            scheme.primaryContainer, scheme.secondaryContainer, scheme.tertiaryContainer,
            scheme.surfaceContainer, scheme.surfaceContainerHigh, scheme.surfaceContainerHighest,
        )
        assertFalse(RosyColors.BrandRose in roles)
    }
}
