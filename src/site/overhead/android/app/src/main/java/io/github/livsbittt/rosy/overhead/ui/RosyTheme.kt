package io.github.livsbittt.rosy.overhead.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Colour values copied from src/hmi/web_common/tokens.css, the only source of colour
 * values (D-129, D-292). Every token colour is written on one line as
 * `Color(0xFFRRGGBB) // --<css-custom-property-name>` so the web_common-owned parity
 * test can parse it; keep that exact form. tokens.css defines a single dark `:root`
 * palette, so there is no light scheme.
 *
 * Aliases in tokens.css: --surface-flat = --ground-soft, --surface-raised = --ground-card,
 * --nominal = --button-primary-bg = --paper, --nominal-quiet = --muted,
 * --focus-ring = --series-primary.
 */
object RosyColors {
    val Ground = Color(0xFF101214) // --ground
    val GroundDeep = Color(0xFF08090B) // --ground-deep
    val GroundRaise = Color(0xFF191B1D) // --ground-raise
    val GroundSoft = Color(0xFF1D1F21) // --ground-soft
    val GroundCard = Color(0xFF2B2D30) // --ground-card
    val GroundCard2 = Color(0xFF35383C) // --ground-card-2
    val Paper = Color(0xFFEEEEEF) // --paper
    val Muted = Color(0xFF9499A0) // --muted

    /** ROSY wordmark only (D-277). Not for status, focus, commands or data. */
    val BrandRose = Color(0xFFF697E7) // --brand-rose

    /** Status colours are for thresholds only; nominal state has no colour (D-82). Crit is a fill with Paper ink. */
    val StatusCrit = Color(0xFFC40921) // --status-crit
    val StatusWarn = Color(0xFFFEB432) // --status-warn
    val StatusOk = Color(0xFF12BB81) // --status-ok

    /** Focus ring and data series; not a status. */
    val SeriesPrimary = Color(0xFF49AFFD) // --series-primary

    /** Ink-alpha lines, derived from Paper exactly as tokens.css derives them: rgba(238, 238, 239, a). */
    val Line08 = Paper.copy(alpha = 0.08f) // derived: --line-08
    val Line14 = Paper.copy(alpha = 0.14f) // derived: --line-14 (= --surface-line, --field-line)
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

@Composable
fun RosyTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = RosyColorScheme, content = content)
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
        shape = RoundedCornerShape(6.dp), // --radius-control
        modifier = modifier.fillMaxWidth(),
    ) {
        Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp))
    }
}
