package io.github.livsbittt.rosy.cam.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.link.LinkState
import io.github.livsbittt.rosy.cam.service.StreamState
import io.github.livsbittt.rosy.cam.settings.SiteLink

/**
 * What the D-741 3 app bar says on a camera sender: the target and the link. Rosy Cam commands
 * nothing, so the bar has no stop seat, and there is no footer.
 */
data class CamBar(
    /** Name of the saved receiver; null before the first pairing. */
    val target: String?,
    /** String resource of the link state. */
    val link: Int,
) {
    /** Nominal states carry no colour (D-82); only the reconnecting state is a caution. */
    val caution: Boolean get() = link == R.string.state_disconnected

    companion object {
        fun from(state: StreamState, siteLink: SiteLink?) = CamBar(
            target = siteLink?.run { listOf(siteName, tlsHost, manualHost).firstOrNull { !it.isNullOrBlank() } },
            link = when {
                !state.running -> R.string.state_stopped
                state.thermalPause -> R.string.state_thermal_pause
                state.previewOnly -> R.string.state_preview_only
                state.link.state == LinkState.STREAMING && !state.transmitting -> R.string.state_standby
                state.link.state == LinkState.STREAMING -> R.string.state_streaming
                state.link.state == LinkState.CONNECTING -> R.string.state_connecting
                else -> R.string.state_disconnected
            },
        )
    }
}

/** App mark and name, then the target; the link state has its own line so a long state is never cut. */
@Composable
fun CamAppBar(bar: CamBar) {
    Column(Modifier.fillMaxWidth().background(RosyColors.GroundDeep)) {
        Row(
            modifier = Modifier.heightIn(min = RosyMetrics.TargetSecondary.dp).padding(horizontal = RosyMetrics.Space4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(RosyMetrics.Space2.dp),
        ) {
            // The mark and the name read as one heading, "Rosy Cam".
            Row(
                modifier = Modifier.semantics(mergeDescendants = true) { heading() },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(RosyMetrics.Space2.dp),
            ) {
                Icon(painterResource(R.drawable.ic_rosy_mark), contentDescription = "Rosy", tint = RosyColors.BrandRose, modifier = Modifier.size(28.dp))
                Text("Cam", style = MaterialTheme.typography.titleLarge)
            }
            bar.target?.let {
                Text(it, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        Text(
            stringResource(bar.link),
            style = MaterialTheme.typography.bodyMedium,
            color = if (bar.caution) RosyColors.StatusWarn else Color.Unspecified,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }.padding(start = RosyMetrics.Space4.dp, end = RosyMetrics.Space4.dp, bottom = RosyMetrics.Space2.dp),
        )
        HorizontalDivider()
    }
}

/** Path position under the bar: the screen's title, in the same place on every screen. */
@Composable
fun CamPath(title: String) {
    Text(
        title,
        style = MaterialTheme.typography.headlineSmall,
        modifier = Modifier.semantics { heading() }.padding(horizontal = RosyMetrics.Space4.dp, vertical = RosyMetrics.Space2.dp),
    )
}
