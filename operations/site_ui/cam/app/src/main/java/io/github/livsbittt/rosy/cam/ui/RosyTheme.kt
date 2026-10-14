package io.github.livsbittt.rosy.cam.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight

/** Semantic facade over generated shared/web/tokens.css values (D-639). */
object RosyColors {
    val Ground = Color(RosyTokenColors.Ground) // --ground
    val GroundDeep = Color(RosyTokenColors.GroundDeep) // --ground-deep
    val GroundRaise = Color(RosyTokenColors.GroundRaise) // --ground-raise
    val GroundSoft = Color(RosyTokenColors.GroundSoft) // --ground-soft
    val GroundCard = Color(RosyTokenColors.GroundCard) // --ground-card
    val GroundCard2 = Color(RosyTokenColors.GroundCard2) // --ground-card-2
    val Paper = Color(RosyTokenColors.Ink) // --ink
    val Muted = Color(RosyTokenColors.InkQuiet) // --ink-quiet

    /** ROSY wordmark and its R mark only (D-277, D-654 3). Not for status, focus, commands or data. */
    val BrandRose = Color(RosyTokenColors.BrandRose) // --brand-rose

    /** Status colours are for thresholds only; nominal state has no colour (D-82). Crit is a fill with Paper ink. */
    val StatusCrit = Color(RosyTokenColors.StatusCrit) // --status-crit
    val StatusWarn = Color(RosyTokenColors.StatusWarn) // --status-warn
    val StatusOk = Color(RosyTokenColors.StatusGood) // --status-good

    /** Focus ring and data series; not a status. */
    val SeriesPrimary = Color(RosyTokenColors.SeriesPrimary) // --series-primary

    /** Ink-alpha lines, derived from Paper exactly as tokens.css derives them: color-mix(in oklab, --ink a%, transparent). */
    val Line08 = Paper.copy(alpha = RosyMetrics.GaugeTrackAlpha) // derived: --gauge-track (ink 8%)
    val Line14 = Paper.copy(alpha = RosyMetrics.Line14Alpha) // derived: --line-14 (= --surface-line). --field-line is --control-line (ink 50%) on the web since D-741.
}

/** Primary command is the brightest neutral, not a hue (tokens.css --button-primary-*). */
val RosyColorScheme: ColorScheme = darkColorScheme(
    primary = RosyColors.Paper,
    onPrimary = RosyColors.Ground,
    primaryContainer = RosyColors.GroundCard,
    onPrimaryContainer = RosyColors.Paper,
    inversePrimary = RosyColors.Ground,
    secondary = RosyColors.Muted,
    onSecondary = RosyColors.Ground,
    secondaryContainer = RosyColors.GroundCard,
    onSecondaryContainer = RosyColors.Paper,
    tertiary = RosyColors.SeriesPrimary,
    onTertiary = RosyColors.Ground,
    tertiaryContainer = RosyColors.GroundCard,
    onTertiaryContainer = RosyColors.Paper,
    background = RosyColors.Ground,
    onBackground = RosyColors.Paper,
    surface = RosyColors.Ground,
    onSurface = RosyColors.Paper,
    surfaceVariant = RosyColors.GroundCard,
    onSurfaceVariant = RosyColors.Muted,
    surfaceTint = RosyColors.Ground,
    inverseSurface = RosyColors.Paper,
    inverseOnSurface = RosyColors.Ground,
    error = RosyColors.StatusCrit,
    onError = RosyColors.Paper,
    errorContainer = RosyColors.StatusCrit,
    onErrorContainer = RosyColors.Paper,
    outline = RosyColors.Line14,
    outlineVariant = RosyColors.Line08,
    scrim = RosyColors.GroundDeep,
    surfaceBright = RosyColors.GroundCard,
    surfaceDim = RosyColors.GroundDeep,
    surfaceContainerLowest = RosyColors.GroundDeep,
    surfaceContainerLow = RosyColors.GroundRaise,
    surfaceContainer = RosyColors.GroundSoft,
    surfaceContainerHigh = RosyColors.GroundCard,
    surfaceContainerHighest = RosyColors.GroundCard2,
)

val RosyButtonShape = RoundedCornerShape(RosyMetrics.RadiusButton.dp)
val RosyButtonPadding = PaddingValues(horizontal = RosyMetrics.InsetButton.dp, vertical = RosyMetrics.Space2.dp)

private fun tokenText(size: Float, weight: Float, leading: Float) = TextStyle(
    fontSize = size.sp, lineHeight = (size * leading).sp, fontWeight = FontWeight(weight.toInt()),
)

private val RosyTypography = Typography(
    displayLarge = tokenText(RosyMetrics.TextDisplay, RosyMetrics.WeightStrong, RosyMetrics.LeadingDense),
    displayMedium = tokenText(RosyMetrics.TextDisplay, RosyMetrics.WeightStrong, RosyMetrics.LeadingDense),
    displaySmall = tokenText(RosyMetrics.TextDisplay, RosyMetrics.WeightStrong, RosyMetrics.LeadingDense),
    headlineLarge = tokenText(RosyMetrics.TextTitle, RosyMetrics.WeightStrong, RosyMetrics.LeadingCompact),
    headlineMedium = tokenText(RosyMetrics.TextTitle, RosyMetrics.WeightStrong, RosyMetrics.LeadingCompact),
    headlineSmall = tokenText(RosyMetrics.TextTitle, RosyMetrics.WeightStrong, RosyMetrics.LeadingCompact),
    titleLarge = tokenText(RosyMetrics.TextTitle, RosyMetrics.WeightStrong, RosyMetrics.LeadingCompact),
    titleMedium = tokenText(RosyMetrics.TextValue, RosyMetrics.WeightMedium, RosyMetrics.LeadingLabel),
    titleSmall = tokenText(RosyMetrics.TextBody, RosyMetrics.WeightMedium, RosyMetrics.LeadingBody),
    bodyLarge = tokenText(RosyMetrics.TextBody, RosyMetrics.WeightRegular, RosyMetrics.LeadingBody),
    bodyMedium = tokenText(RosyMetrics.TextBody, RosyMetrics.WeightRegular, RosyMetrics.LeadingBody),
    bodySmall = tokenText(RosyMetrics.TextLabel, RosyMetrics.WeightRegular, RosyMetrics.LeadingCopy),
    labelLarge = tokenText(RosyMetrics.TextLabel, RosyMetrics.WeightLabel, RosyMetrics.LeadingControl),
    labelMedium = tokenText(RosyMetrics.TextLabel, RosyMetrics.WeightLabel, RosyMetrics.LeadingControl),
    labelSmall = tokenText(RosyMetrics.TextMicro, RosyMetrics.WeightLabel, RosyMetrics.LeadingLabel),
)

private val RosyShapes = Shapes(
    extraSmall = RoundedCornerShape(RosyMetrics.RadiusControl.dp),
    small = RoundedCornerShape(RosyMetrics.RadiusButton.dp),
    medium = RoundedCornerShape(RosyMetrics.RadiusPanel.dp),
    large = RoundedCornerShape(RosyMetrics.RadiusPanel.dp),
    extraLarge = RoundedCornerShape(RosyMetrics.RadiusPanel.dp),
)

@Composable
fun RosyTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = RosyColorScheme, typography = RosyTypography, shapes = RosyShapes) {
        // Screens draw on a plain Column, not a Surface, so set the ink here; otherwise Text
        // falls back to LocalContentColor's default (black) on the dark ground.
        CompositionLocalProvider(LocalContentColor provides RosyColorScheme.onBackground, content = content)
    }
}

/**
 * Danger is a fill, not a text colour (tokens.css: crit carries Paper ink, 5.3:1);
 * crit text on the ground would be about 3:1.
 */
@Composable
fun CritMessage(text: String, modifier: Modifier = Modifier) {
    Surface(
        color = MaterialTheme.colorScheme.error,
        contentColor = MaterialTheme.colorScheme.onError,
        shape = RoundedCornerShape(RosyMetrics.RadiusControl.dp), // --radius-control
        modifier = modifier.fillMaxWidth(),
    ) {
        Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(horizontal = RosyMetrics.InsetButton.dp, vertical = RosyMetrics.Space2.dp))
    }
}
