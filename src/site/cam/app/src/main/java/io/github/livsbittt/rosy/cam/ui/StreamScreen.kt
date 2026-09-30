package io.github.livsbittt.rosy.cam.ui

import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import androidx.camera.view.PreviewView
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.TextButton
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.draw.clip
import io.github.livsbittt.rosy.cam.health.DeviceHealth
import io.github.livsbittt.rosy.cam.health.HealthText
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.link.LinkState
import io.github.livsbittt.rosy.cam.service.CameraSessionPlan
import io.github.livsbittt.rosy.cam.service.StreamService
import io.github.livsbittt.rosy.cam.service.StreamState
import io.github.livsbittt.rosy.cam.settings.PairingUri

@Composable
fun StreamScreen(
    state: StreamState,
    pairing: PairingUri?,
    localError: String?,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    // Keep the screen on while streaming (design section 5).
    val view = LocalView.current
    DisposableEffect(state.running) {
        view.keepScreenOn = state.running
        onDispose { view.keepScreenOn = false }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .safeDrawingPadding()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .background(RosyColors.GroundDeep),
            contentAlignment = Alignment.Center,
        ) {
            if (state.running) {
                CameraPreview(Modifier.fillMaxSize())
            } else {
                Text(
                    stringResource(R.string.preview_idle),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
        }

        StatusPanel(state, pairing, localError, onStop, onOpenSettings)

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            // Opens read-only while the camera runs; the settings screen says how to unlock it.
            OutlinedButton(
                onClick = onOpenSettings,
                modifier = Modifier.height(72.dp),
            ) {
                Text(stringResource(R.string.button_settings))
            }
            if (state.running) {
                Button(
                    // Stopping is routine and reversible: neutral primary, not the crit fill (D-277 3).
                    onClick = onStop,
                    modifier = Modifier.weight(1f).height(72.dp),
                ) {
                    Text(stringResource(R.string.button_stop), fontSize = 22.sp)
                }
            } else {
                Button(
                    onClick = onStart,
                    enabled = CameraSessionPlan.from(pairing).startCamera,
                    modifier = Modifier.weight(1f).height(72.dp),
                ) {
                    Text(stringResource(R.string.button_start), fontSize = 22.sp)
                }
            }
        }
    }
}

@Composable
private fun StatusPanel(
    state: StreamState,
    pairing: PairingUri?,
    localError: String?,
    onStop: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val link = state.link
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        val stateText = when {
            !state.running -> R.string.state_stopped
            state.previewOnly -> R.string.state_preview_only
            link.state == LinkState.STREAMING -> R.string.state_streaming
            link.state == LinkState.CONNECTING -> R.string.state_connecting
            else -> R.string.state_disconnected
        }
        // Nominal states carry no colour (D-82); only the reconnecting state is a caution.
        Text(
            stringResource(stateText),
            style = MaterialTheme.typography.headlineSmall,
            color = if (stateText == R.string.state_disconnected) RosyColors.StatusWarn else Color.Unspecified,
        )
        // While stopped, show the saved pairing: state.target still holds the last run's target,
        // which is stale once the operator saves a new address.
        val saved = pairing?.let { "${it.host}:${it.port} · ${it.source}" }
        val target = if (state.running) state.target ?: saved else saved
        Text(
            when {
                state.previewOnly -> stringResource(R.string.target_preview_only)
                target != null -> stringResource(R.string.target_label, target)
                else -> stringResource(R.string.target_none)
            },
            style = MaterialTheme.typography.bodyMedium,
        )
        if (state.running) {
            val res = LocalContext.current.resources
            state.lens?.let { LensText.line(res, it) }?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
            if (state.lensSwitchFailed) {
                Text(stringResource(R.string.lens_switch_failed), color = RosyColors.StatusWarn, style = MaterialTheme.typography.bodyMedium)
            }
        }
        state.health?.let { HealthPanel(it) }
        val site = link.site
        // Per camera session: once the receiver has reported a marker, an empty report is a real 0/4.
        var markersReported by rememberSaveable(state.running) { mutableStateOf(false) }
        LaunchedEffect(site) {
            if (site != null && CornerGuide.reportsMarkers(site)) markersReported = true
        }
        if (state.running && link.state == LinkState.STREAMING && site != null) {
            if (markersReported || CornerGuide.reportsMarkers(site)) {
                val guide = CornerGuide.from(site)
                InstallGuide(guide)
                if (LensAdvice.suggestWide(state.lens, state.wideAvailable, guide, markersReported = true)) {
                    Text(stringResource(R.string.guide_lens_wide), style = MaterialTheme.typography.bodyMedium)
                }
            } else {
                Text(
                    stringResource(R.string.guide_markers_unreported),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (!state.previewOnly) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Text(stringResource(R.string.stat_fps, link.sentFps))
                Text(stringResource(R.string.stat_kbps, link.kbps))
                Text(stringResource(R.string.stat_skipped, link.dropped))
            }
            Text(
                stringResource(R.string.stat_config, link.config.fps, link.config.width, link.config.jpegQuality),
                style = MaterialTheme.typography.bodySmall,
            )
            val sentQuality = link.sentQuality
            if (state.running && sentQuality != null && sentQuality < link.config.jpegQuality) {
                Text(
                    stringResource(R.string.stat_quality_auto, sentQuality, link.config.jpegQuality),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (link.dropped > 0) {
                Text(
                    stringResource(R.string.stat_skipped_hint),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        val wifiConnected = rememberWifiConnected()
        val guidance = state.error?.let(ProblemGuide::forStream)
            // A stopped session is not reconnecting, whatever the link's last state said.
            ?: link.error?.let { ProblemGuide.forLink(it, link.stopped || !state.running, wifiConnected) }
        when {
            localError != null -> CritMessage(localError)
            guidance != null -> ProblemMessage(guidance, pairing, state.running, onStop, onOpenSettings)
        }
    }
}

@Composable
private fun HealthPanel(health: DeviceHealth) {
    val res = LocalContext.current.resources
    Text(HealthText.line(res, health), style = MaterialTheme.typography.bodyMedium)
    // The text states the condition; the warn colour only reinforces it (D-82).
    health.warnings.forEach { w ->
        Text(HealthText.warning(res, w, health), color = RosyColors.StatusWarn, style = MaterialTheme.typography.bodyMedium)
    }
}

/** Corner markers as dots: filled = seen, ring = not seen. Shape carries the meaning, not colour (D-82). */
@Composable
private fun InstallGuide(guide: CornerGuide) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            guide.dots.forEach { seen ->
                val dot = Modifier.size(12.dp).clip(CircleShape)
                Box(
                    if (seen) {
                        dot.background(MaterialTheme.colorScheme.onSurface)
                    } else {
                        dot.border(2.dp, MaterialTheme.colorScheme.onSurfaceVariant, CircleShape)
                    },
                )
            }
        }
        Text(
            when (guide.progress) {
                CornerGuide.Progress.NONE -> stringResource(R.string.guide_corners_none, guide.needed)
                CornerGuide.Progress.PARTIAL ->
                    stringResource(R.string.guide_corners_partial, guide.seenCount, guide.needed, guide.seenIds)
                CornerGuide.Progress.COMPLETE -> stringResource(R.string.guide_corners_complete, guide.seenCount, guide.needed)
            },
            style = MaterialTheme.typography.bodyMedium,
        )
    }
    Text(
        if (guide.robots.isEmpty()) {
            stringResource(R.string.guide_robots_none)
        } else {
            stringResource(R.string.guide_robots, guide.robotIds)
        },
        style = MaterialTheme.typography.bodySmall,
    )
}

/** One sentence naming the next step, an optional action, and the raw detail behind "자세히". */
@Composable
private fun ProblemMessage(
    guidance: Guidance,
    pairing: PairingUri?,
    running: Boolean,
    onStop: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    var showDetail by rememberSaveable(guidance.problem) { mutableStateOf(false) }
    val address = pairing?.let { "${it.host}:${it.port}" } ?: ""
    val text = when (guidance.problem) {
        Problem.NO_WIFI -> stringResource(R.string.problem_no_wifi)
        Problem.UNREACHABLE -> stringResource(R.string.problem_unreachable, address)
        Problem.REFUSED -> stringResource(R.string.problem_refused, address)
        Problem.UNKNOWN_HOST -> stringResource(R.string.problem_unknown_host, pairing?.host ?: "")
        Problem.TLS -> stringResource(
            if (pairing?.secure == true && pairing.pin == null) R.string.problem_tls_unpinned else R.string.problem_tls,
        )
        Problem.TLS_PIN -> stringResource(R.string.problem_tls_pin)
        Problem.UNAUTHORIZED -> stringResource(R.string.problem_unauthorized)
        Problem.REPLACED -> stringResource(R.string.problem_replaced, pairing?.source ?: "")
        Problem.PROTOCOL_MISMATCH -> stringResource(R.string.problem_protocol_mismatch)
        Problem.BUSY -> stringResource(R.string.problem_busy)
        Problem.INVALID_CONFIG -> stringResource(R.string.problem_invalid_config)
        Problem.CLOSED -> stringResource(R.string.problem_closed)
        Problem.NETWORK_OTHER -> stringResource(R.string.problem_network_other)
        Problem.NOT_PAIRED -> stringResource(R.string.problem_not_paired)
        Problem.CAMERA -> stringResource(R.string.problem_camera)
        Problem.FOREGROUND_DENIED -> stringResource(R.string.problem_foreground)
    }
    val retrying = if (guidance.retrying) "\n" + stringResource(R.string.problem_retrying) else ""
    CritMessage(text + retrying)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        if (guidance.step == NextStep.OPEN_SETTINGS) {
            if (ProblemGuide.stopsCameraFirst(guidance.problem, running)) {
                OutlinedButton(onClick = { onStop(); onOpenSettings() }) {
                    Text(stringResource(R.string.button_stop_and_open_settings))
                }
            } else {
                OutlinedButton(onClick = onOpenSettings) { Text(stringResource(R.string.button_open_settings)) }
            }
        }
        if (guidance.detail != null) {
            TextButton(onClick = { showDetail = !showDetail }) {
                Text(stringResource(if (showDetail) R.string.button_details_hide else R.string.button_details))
            }
        }
    }
    if (showDetail && guidance.detail != null) {
        Text(guidance.detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/**
 * True while any Wi-Fi or Ethernet network is up, whether or not it is the default network or
 * has internet: a closed site Wi-Fi without internet often loses "default" to mobile data.
 */
@Composable
private fun rememberWifiConnected(): Boolean {
    val context = LocalContext.current
    val connectivity = remember(context) { context.getSystemService(ConnectivityManager::class.java) }
    val lan = remember { LanNetworks() }
    var connected by remember {
        val caps = connectivity.getNetworkCapabilities(connectivity.activeNetwork)
        mutableStateOf(
            caps != null &&
                (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)),
        )
    }
    DisposableEffect(connectivity) {
        // Transports are OR-ed; dropping INTERNET keeps a no-internet site Wi-Fi in the request.
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                connected = lan.onAvailable(network.toString())
            }

            override fun onLost(network: Network) {
                connected = lan.onLost(network.toString())
            }
        }
        connectivity.registerNetworkCallback(request, callback)
        onDispose { connectivity.unregisterNetworkCallback(callback) }
    }
    return connected
}

/** Binds a PreviewView to the running session, and detaches it while the activity is stopped. */
@Composable
private fun CameraPreview(modifier: Modifier) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember {
        PreviewView(context).apply {
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
            scaleType = PreviewView.ScaleType.FIT_CENTER
        }
    }
    DisposableEffect(lifecycleOwner, previewView) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> StreamService.previewSurface.value = previewView.surfaceProvider
                Lifecycle.Event.ON_STOP -> StreamService.previewSurface.value = null
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            StreamService.previewSurface.value = null
        }
    }
    AndroidView(factory = { previewView }, modifier = modifier)
}
