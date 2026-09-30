package io.github.livsbittt.rosy.cam

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import io.github.livsbittt.rosy.cam.camera.LensChoice
import io.github.livsbittt.rosy.cam.service.StreamService
import io.github.livsbittt.rosy.cam.settings.PairingUri
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import io.github.livsbittt.rosy.cam.ui.RosyTheme
import io.github.livsbittt.rosy.cam.ui.SettingsScreen
import io.github.livsbittt.rosy.cam.ui.StreamScreen
import io.github.livsbittt.rosy.cam.ui.invalidText
import io.github.livsbittt.rosy.cam.ui.rememberLan
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
        if (savedInstanceState == null) {
            handlePairingIntent(intent)
        } else {
            restorePendingPairing(savedInstanceState)
        }
        setContent {
            RosyTheme {
                OverheadApp()
            }
        }
    }

    /**
     * Keeps an unconfirmed deep link across rotation and other configuration changes. It is
     * stored as the same rosyov:// text that arrived in the intent, which the system already holds.
     */
    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        pendingPairing.value?.let { outState.putString(KEY_PENDING_PAIRING, it.toUri()) }
        deepLinkInvalid.value?.let { outState.putString(KEY_DEEP_LINK_INVALID, it) }
    }

    private fun restorePendingPairing(state: Bundle) {
        state.getString(KEY_PENDING_PAIRING)?.let { uri ->
            (PairingUri.parse(uri) as? PairingUri.Parsed.Valid)?.let { pendingPairing.value = it.pairing }
        }
        deepLinkInvalid.value = state.getString(KEY_DEEP_LINK_INVALID)
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
        val siteLink by settings.siteLink.collectAsStateWithLifecycle(initialValue = null)
        val pairing = siteLink?.toPairing()
        // The Wi-Fi now: "not connected" check, and the pairing-time subnet saved for diagnosis only.
        val lan = rememberLan()
        val lens by settings.lens.collectAsStateWithLifecycle(initialValue = null)
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
                currentLink = siteLink,
                locked = state.running,
                lens = LensChoice.orDefault(lens),
                onLens = { choice -> scope.launch { settings.saveLens(choice) } },
                onSave = { p, siteName, fresh ->
                    // A settings edit keeps the pairing-time subnet; only a fresh pairing records the current one.
                    val subnet = if (fresh) lan?.subnet else null
                    scope.launch { settings.save(p, siteName, subnet) }
                },
                onBack = { showSettings = false },
            )
        } else {
            StreamScreen(
                state = state,
                siteLink = siteLink,
                lan = lan,
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
                text = {
                    val body = stringResource(R.string.pair_body, p.host, p.port, p.source)
                    val pin = p.pin?.let { "\n" + stringResource(R.string.pair_body_pin, it.take(PIN_PREVIEW)) }.orEmpty()
                    // Warn when the new link is weaker than what is saved: it drops the pin or TLS.
                    val lost = when {
                        pairing?.secure == true && !p.secure -> R.string.pair_downgrade_tls
                        pairing?.pin != null && p.pin == null -> R.string.pair_downgrade_pin
                        else -> null
                    }
                    val downgrade = lost?.let { "\n\n" + stringResource(R.string.pair_downgrade, stringResource(it)) }.orEmpty()
                    Text(body + pin + downgrade)
                },
                confirmButton = {
                    TextButton(
                        enabled = !state.running,
                        onClick = {
                            pendingPairing.value = null
                            val subnet = lan?.subnet
                            lifecycleScope.launch { settings.save(p, pairingSubnet = subnet) }
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

private const val KEY_PENDING_PAIRING = "pending_pairing"
private const val KEY_DEEP_LINK_INVALID = "deep_link_invalid"

/** `sha256/` plus 12 base64url characters: enough to compare by eye with the site's printout. */
internal const val PIN_PREVIEW = 19
