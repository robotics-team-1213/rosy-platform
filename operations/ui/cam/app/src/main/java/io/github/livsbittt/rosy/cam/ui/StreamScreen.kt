package io.github.livsbittt.rosy.cam.ui

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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.camera.ExposureVerdict
import io.github.livsbittt.rosy.cam.camera.Antibanding
import io.github.livsbittt.rosy.cam.camera.TuningMode
import io.github.livsbittt.rosy.cam.link.LinkState
import io.github.livsbittt.rosy.cam.service.CameraSessionPlan
import io.github.livsbittt.rosy.cam.service.StreamService
import io.github.livsbittt.rosy.cam.link.SiteRoute
import io.github.livsbittt.rosy.cam.service.StreamState
import io.github.livsbittt.rosy.cam.settings.SiteLink
import android.content.ClipData
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File
import android.widget.Toast

@Composable
fun StreamScreen(
    state: StreamState,
    siteLink: SiteLink?,
    /** Host of a stored pairing that is no longer valid (non-.local name, D-391 1); the operator must re-pair. */
    rejectedHost: String?,
    /** Non-.local name dropped from a stored pairing that still dials its manual IP; re-pairing is advised. */
    droppedTlsHost: String?,
    lan: LanSnapshot?,
    localError: String?,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onOpenSettings: () -> Unit,
    onScreenOff: () -> Unit = {},
) {
    val pairing = siteLink?.toPairing()
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
                .weight(0.75f)
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

        Column(
            modifier = Modifier.fillMaxWidth().weight(1f, fill = false).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            StatusPanel(state, siteLink, rejectedHost, droppedTlsHost, lan, localError, onStop, onOpenSettings)

            if (state.running) {
                val light = state.lighting
                Text(stringResource(when {
                    !light.supported -> R.string.light_unsupported
                    light.message != null -> R.string.light_error
                    !light.requested -> R.string.light_disabled
                    light.torchOn -> R.string.light_on
                    light.dark -> R.string.light_dark
                    else -> R.string.light_ready
                }), style = MaterialTheme.typography.bodySmall)
                val tuning = state.tuning
                val applied = tuning.applied
                when (tuning.mode) {
                    null -> null
                    TuningMode.VISION -> stringResource(R.string.tuning_vision,
                        listOfNotNull(
                            stringResource(if (applied.locked) R.string.tuning_locked else R.string.tuning_adjusting),
                            tuning.evText,
                            if (applied.antibanding == Antibanding.HZ60) "60Hz" else null,
                        ).joinToString(" · "))
                    TuningMode.LOCAL -> stringResource(if (tuning.localAssist) R.string.tuning_wait_local else R.string.tuning_wait_default)
                    TuningMode.DISABLED -> stringResource(R.string.tuning_disabled)
                    TuningMode.THERMAL_HOLD -> stringResource(R.string.tuning_thermal_hold, tuning.evText)
                }?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                val exposure = state.exposure
                if (exposure.supported) {
                    // While Vision sets the camera the D-544 assist is idle; its line would only mislead.
                    if (tuning.mode != TuningMode.VISION) Text(stringResource(when {
                        !exposure.enabled -> R.string.exposure_off
                        exposure.verdict == ExposureVerdict.OVER -> R.string.exposure_over
                        exposure.verdict == ExposureVerdict.UNDER -> R.string.exposure_under
                        else -> R.string.exposure_ok
                    }) + if (exposure.enabled && exposure.index != 0) " · EV ${exposure.index}" else "",
                        style = MaterialTheme.typography.bodySmall)
                    OutlinedButton(onClick = { StreamService.setExposureAssist(!exposure.enabled) }, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(if (exposure.enabled) R.string.exposure_disable else R.string.exposure_enable))
                    }
                }
                Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedButton(onClick = { StreamService.requestLight(!light.requested) }, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(if (light.requested) R.string.light_disable else R.string.light_enable))
                    }
                    Button(onClick = { StreamService.savePhoto() }, modifier = Modifier.fillMaxWidth(),
                        enabled = !state.previewOnly && !state.photoSaving) {
                        Text(stringResource(if (state.photoSaving) R.string.photo_saving else R.string.photo_save))
                    }
                }
            }
            if (state.photoFailed) Text(stringResource(R.string.photo_failed), color = RosyColors.StatusWarn)
            state.photoName?.let { name ->
                val context = LocalContext.current
                OutlinedButton(onClick = {
                    try {
                        val file = File(context.filesDir, "photos/$name")
                        require(File(name).name == name && file.isFile)
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.photos", file)
                        val intent = Intent(Intent.ACTION_SEND).apply {
                            type = "image/jpeg"
                            putExtra(Intent.EXTRA_STREAM, uri)
                            clipData = ClipData.newRawUri("Rosy Cam photo", uri)
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        }
                        context.startActivity(Intent.createChooser(intent, context.getString(R.string.photo_share)))
                    } catch (_: Exception) {
                        Toast.makeText(context, R.string.photo_share_failed, Toast.LENGTH_LONG).show()
                    }
                }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.photo_share)) }
            }

        }

        if (state.running) OutlinedButton(onClick = onScreenOff, modifier = Modifier.fillMaxWidth()) { Text("화면 끄기 · 촬영 유지") }

        Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            // Opens read-only while the camera runs; the settings screen says how to unlock it.
            OutlinedButton(
                onClick = onOpenSettings,
                modifier = Modifier.fillMaxWidth().height(64.dp),
            ) {
                Text(stringResource(R.string.button_settings))
            }
            if (state.running) {
                Button(
                    // Stopping is routine and reversible: neutral primary, not the crit fill (D-277 3).
                    onClick = onStop,
                    modifier = Modifier.fillMaxWidth().height(64.dp),
                ) {
                    Text(stringResource(R.string.button_stop), fontSize = 22.sp)
                }
            } else {
                Button(
                    onClick = onStart,
                    enabled = CameraSessionPlan.from(pairing).startCamera,
                    modifier = Modifier.fillMaxWidth().height(64.dp),
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
    siteLink: SiteLink?,
    rejectedHost: String?,
    droppedTlsHost: String?,
    lan: LanSnapshot?,
    localError: String?,
    onStop: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val pairing = siteLink?.toPairing()
    val link = state.link
    var showDiagnostics by rememberSaveable { mutableStateOf(false) }
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
        // A pairing saved under the old rules that D-391 no longer accepts: say "re-pair", not "never paired".
        if (siteLink == null && rejectedHost != null) {
            CritMessage(stringResource(R.string.target_rejected, rejectedHost))
        }
        // Salvaged: the old name is gone but the manual IP still dials. A soft note, not the re-pair alarm.
        val salvagedIp = siteLink?.manualHost
        if (droppedTlsHost != null && salvagedIp != null) {
            Text(
                stringResource(R.string.target_salvaged, droppedTlsHost, salvagedIp),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (state.running) {
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
            Text(stringResource(R.string.stat_fps, link.sentFps), style = MaterialTheme.typography.bodyMedium)
            TextButton(onClick = { showDiagnostics = !showDiagnostics }) {
                Text(if (showDiagnostics) "연결·송출 정보 접기" else "연결·송출 정보 보기")
            }
            if (showDiagnostics) {
                if (state.running) {
                    when (val route = state.route) {
                        is SiteRoute.Discovered -> stringResource(
                            R.string.target_route_mdns,
                            route.sighting.addresses.joinToString { it.hostAddress.orEmpty() },
                        )
                        is SiteRoute.Manual -> stringResource(
                            if (route.afterBrowse) R.string.target_route_manual else R.string.target_route_manual_only,
                            route.address.hostAddress.orEmpty(),
                        )
                        else -> null
                    }?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    val res = LocalContext.current.resources
                    state.lens?.let { LensText.line(res, it) }?.let {
                        Text(it, style = MaterialTheme.typography.bodyMedium)
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
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
            }
            if (link.dropped > 0) {
                Text(
                    stringResource(R.string.stat_skipped_hint),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        val guidance = state.error?.let(ProblemGuide::forStream)
            // A stopped session is not reconnecting, whatever the link's last state said.
            ?: link.error?.let { ProblemGuide.forLink(it, link.stopped || !state.running, wifiConnected = lan != null, route = state.route) }
        when {
            localError != null -> CritMessage(localError)
            guidance != null -> ProblemMessage(guidance, siteLink, lan, state.running, onStop, onOpenSettings)
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
    siteLink: SiteLink?,
    lan: LanSnapshot?,
    running: Boolean,
    onStop: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val pairing = siteLink?.toPairing()
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
        Problem.NOT_DISCOVERED -> notDiscoveredText(lan, siteLink?.pairingSubnet)
        Problem.SITE_CONFLICT -> stringResource(R.string.problem_site_conflict, siteLink?.tlsHost ?: "")
        Problem.UNAUTHORIZED -> stringResource(R.string.problem_unauthorized)
        Problem.FORBIDDEN -> stringResource(R.string.problem_forbidden)
        Problem.REPLACED -> stringResource(R.string.problem_replaced, pairing?.source ?: "")
        Problem.PROTOCOL_MISMATCH -> stringResource(R.string.problem_protocol_mismatch)
        Problem.BUSY -> stringResource(R.string.problem_busy)
        Problem.SITE_CHECKING -> stringResource(R.string.problem_site_checking)
        Problem.INVALID_CONFIG -> stringResource(R.string.problem_invalid_config)
        Problem.CLOSED -> stringResource(R.string.problem_closed)
        Problem.NETWORK_OTHER -> stringResource(R.string.problem_network_other)
        Problem.NOT_PAIRED -> stringResource(R.string.problem_not_paired)
        Problem.CAMERA -> stringResource(R.string.problem_camera)
        Problem.FOREGROUND_DENIED -> stringResource(R.string.problem_foreground)
    }
    // mDNS found nothing and the "수동 주소" fallback failed as well: say both, not-found first.
    val manual = siteLink?.manualHost.orEmpty()
    val manualLine = when (guidance.manualFailure) {
        Problem.UNREACHABLE -> "\n" + stringResource(R.string.problem_manual_unreachable, manual)
        Problem.REFUSED -> "\n" + stringResource(R.string.problem_manual_refused, manual)
        Problem.NETWORK_OTHER -> "\n" + stringResource(R.string.problem_manual_other, manual)
        else -> ""
    }
    val retrying = if (guidance.retrying) "\n" + stringResource(R.string.problem_retrying) else ""
    CritMessage(text + manualLine + retrying)
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
 * "사이트가 이 Wi-Fi에서 보이지 않습니다" plus the network now and at pairing time, so a same-SSID other
 * network (another AP or hotspot) is obvious (D-391 1, 2026-10-01 tablet).
 */
@Composable
private fun notDiscoveredText(lan: LanSnapshot?, pairingSubnet: String?): String {
    val now = lan?.subnet?.let { subnet ->
        lan.gateway?.let { stringResource(R.string.network_with_gateway, subnet, it) } ?: subnet
    } ?: stringResource(R.string.network_unknown)
    val kind = ProblemGuide.notDiscoveredHint(lan, pairingSubnet)
    val hint = when (kind) {
        ProblemGuide.NotDiscoveredHint.OTHER_SUBNET -> stringResource(R.string.problem_not_discovered_other, now, pairingSubnet ?: "")
        ProblemGuide.NotDiscoveredHint.SAME_SUBNET -> stringResource(R.string.problem_not_discovered_same, now)
        ProblemGuide.NotDiscoveredHint.UNKNOWN -> stringResource(R.string.problem_not_discovered_unknown, now)
    }
    val headline = when (ProblemGuide.notDiscoveredHeadline(kind)) {
        ProblemGuide.NotDiscoveredHeadline.OTHER_WIFI -> stringResource(R.string.problem_not_discovered)
        ProblemGuide.NotDiscoveredHeadline.MDNS_SILENT -> stringResource(R.string.problem_not_discovered_mdns)
    }
    return headline + "\n" + hint
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
