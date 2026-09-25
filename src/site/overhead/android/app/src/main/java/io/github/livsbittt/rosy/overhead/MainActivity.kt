package io.github.livsbittt.rosy.overhead

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import io.github.livsbittt.rosy.overhead.service.StreamService
import io.github.livsbittt.rosy.overhead.settings.PairingUri
import io.github.livsbittt.rosy.overhead.settings.SettingsStore
import io.github.livsbittt.rosy.overhead.ui.SettingsScreen
import io.github.livsbittt.rosy.overhead.ui.StreamScreen
import io.github.livsbittt.rosy.overhead.ui.invalidText
import kotlinx.coroutines.launch

/**
 * Single activity: stream screen + settings screen, runtime permissions, and the
 * `rosyov://` pairing deep link (D-261 6). A deep link is only saved after the operator
 * confirms, so a stray link cannot silently redirect frames to another host.
 */
class MainActivity : ComponentActivity() {
    private val pendingPairing = mutableStateOf<PairingUri?>(null)
    private val deepLinkInvalid = mutableStateOf<String?>(null)
    private lateinit var settings: SettingsStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settings = SettingsStore(applicationContext)
        if (savedInstanceState == null) handlePairingIntent(intent)
        setContent {
            OverheadTheme {
                OverheadApp()
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handlePairingIntent(intent)
    }

    private fun handlePairingIntent(intent: Intent?) {
        if (intent?.action != Intent.ACTION_VIEW) return
        val data = intent.data ?: return
        if (!data.scheme.equals(PairingUri.SCHEME, ignoreCase = true)) return
        when (val parsed = PairingUri.parse(data.toString())) {
            is PairingUri.Parsed.Valid -> {
                pendingPairing.value = parsed.pairing
                deepLinkInvalid.value = null
            }
            is PairingUri.Parsed.Invalid -> deepLinkInvalid.value = parsed.reason
        }
    }

    private fun hasCamera(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    @Composable
    private fun OverheadApp() {
        val state by StreamService.state.collectAsStateWithLifecycle()
        val pairing by settings.pairing.collectAsStateWithLifecycle(initialValue = null)
        var showSettings by remember { mutableStateOf(false) }
        var localError by remember { mutableStateOf<String?>(null) }
        val scope = rememberCoroutineScope()
        val permissionDenied = stringResource(R.string.error_camera_permission)

        val permissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
            // Notifications are optional; the camera is not.
            if (result[Manifest.permission.CAMERA] == true || hasCamera()) {
                localError = null
                StreamService.start(this)
            } else {
                localError = permissionDenied
            }
        }

        val onStart = {
            localError = null
            val needed = buildList {
                if (!hasCamera()) add(Manifest.permission.CAMERA)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                    ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.POST_NOTIFICATIONS) !=
                    PackageManager.PERMISSION_GRANTED
                ) {
                    add(Manifest.permission.POST_NOTIFICATIONS)
                }
            }
            if (needed.isEmpty()) StreamService.start(this) else permissions.launch(needed.toTypedArray())
        }

        if (showSettings) {
            SettingsScreen(
                current = pairing,
                locked = state.running,
                onSave = { p -> scope.launch { settings.save(p) } },
                onBack = { showSettings = false },
            )
        } else {
            StreamScreen(
                state = state,
                pairing = pairing,
                localError = localError,
                onStart = onStart,
                onStop = { StreamService.stop(this) },
                onOpenSettings = { showSettings = true },
            )
        }

        pendingPairing.value?.let { p ->
            AlertDialog(
                onDismissRequest = { pendingPairing.value = null },
                title = { Text(stringResource(R.string.pair_title)) },
                text = { Text(stringResource(R.string.pair_body, p.host, p.port, p.source)) },
                confirmButton = {
                    TextButton(
                        enabled = !state.running,
                        onClick = {
                            pendingPairing.value = null
                            lifecycleScope.launch { settings.save(p) }
                        },
                    ) { Text(stringResource(R.string.pair_save)) }
                },
                dismissButton = {
                    TextButton(onClick = { pendingPairing.value = null }) { Text(stringResource(R.string.pair_cancel)) }
                },
            )
        }

        deepLinkInvalid.value?.let { reason ->
            AlertDialog(
                onDismissRequest = { deepLinkInvalid.value = null },
                text = { Text(stringResource(R.string.pair_invalid, invalidText(reason))) },
                confirmButton = {
                    TextButton(onClick = { deepLinkInvalid.value = null }) { Text(stringResource(R.string.pair_cancel)) }
                },
            )
        }
    }
}

@Composable
private fun OverheadTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme(),
        content = content,
    )
}
