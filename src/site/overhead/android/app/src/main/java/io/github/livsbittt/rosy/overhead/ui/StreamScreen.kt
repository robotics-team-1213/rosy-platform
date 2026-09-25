package io.github.livsbittt.rosy.overhead.ui

import androidx.camera.view.PreviewView
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
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
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
import io.github.livsbittt.rosy.overhead.R
import io.github.livsbittt.rosy.overhead.link.LinkError
import io.github.livsbittt.rosy.overhead.link.LinkState
import io.github.livsbittt.rosy.overhead.service.StreamError
import io.github.livsbittt.rosy.overhead.service.StreamService
import io.github.livsbittt.rosy.overhead.service.StreamState
import io.github.livsbittt.rosy.overhead.settings.PairingUri

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
                .background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            if (state.running) {
                CameraPreview(Modifier.fillMaxSize())
            } else {
                Text(stringResource(R.string.preview_idle), color = Color.White, textAlign = TextAlign.Center)
            }
        }

        StatusPanel(state, pairing, localError)

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(
                onClick = onOpenSettings,
                enabled = !state.running,
                modifier = Modifier.height(72.dp),
            ) {
                Text(stringResource(R.string.button_settings))
            }
            if (state.running) {
                Button(
                    onClick = onStop,
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                    modifier = Modifier.weight(1f).height(72.dp),
                ) {
                    Text(stringResource(R.string.button_stop), fontSize = 22.sp)
                }
            } else {
                Button(
                    onClick = onStart,
                    enabled = pairing != null,
                    modifier = Modifier.weight(1f).height(72.dp),
                ) {
                    Text(stringResource(R.string.button_start), fontSize = 22.sp)
                }
            }
        }
    }
}

@Composable
private fun StatusPanel(state: StreamState, pairing: PairingUri?, localError: String?) {
    val link = state.link
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        val stateText = when {
            !state.running -> R.string.state_stopped
            link.state == LinkState.STREAMING -> R.string.state_streaming
            link.state == LinkState.CONNECTING -> R.string.state_connecting
            else -> R.string.state_disconnected
        }
        Text(stringResource(stateText), style = MaterialTheme.typography.headlineSmall)
        val target = state.target ?: pairing?.let { "${it.host}:${it.port} · ${it.source}" }
        Text(
            if (target != null) stringResource(R.string.target_label, target) else stringResource(R.string.target_none),
            style = MaterialTheme.typography.bodyMedium,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(stringResource(R.string.stat_fps, link.sentFps))
            Text(stringResource(R.string.stat_kbps, link.kbps))
            Text(stringResource(R.string.stat_dropped, link.dropped))
        }
        Text(
            stringResource(R.string.stat_config, link.config.fps, link.config.width, link.config.jpegQuality),
            style = MaterialTheme.typography.bodySmall,
        )
        val error = localError ?: errorText(state.error) ?: errorText(link.error)
        if (error != null) {
            Text(
                stringResource(R.string.last_error, error),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
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

@Composable
private fun errorText(error: StreamError?): String? = when (error) {
    null -> null
    StreamError.NotPaired -> stringResource(R.string.error_not_paired)
    is StreamError.Camera -> stringResource(R.string.error_camera, error.message)
    is StreamError.ForegroundDenied -> stringResource(R.string.error_foreground, error.message)
}

@Composable
private fun errorText(error: LinkError?): String? = when (error) {
    null -> null
    LinkError.Unauthorized -> stringResource(R.string.error_unauthorized)
    LinkError.ProtocolMismatch -> stringResource(R.string.error_protocol_mismatch)
    LinkError.Replaced -> stringResource(R.string.error_replaced)
    is LinkError.InvalidConfig -> stringResource(R.string.error_invalid_config, error.field)
    is LinkError.Network -> stringResource(R.string.error_network, error.detail)
    is LinkError.Closed -> stringResource(R.string.error_closed, error.code, error.reason)
}
