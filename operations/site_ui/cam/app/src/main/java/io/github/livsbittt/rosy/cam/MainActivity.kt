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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.background
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.res.stringResource
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import androidx.activity.viewModels
import io.github.livsbittt.rosy.cam.camera.LensChoice
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.pairing.PairingState
import io.github.livsbittt.rosy.cam.pairing.PairingViewModel
import io.github.livsbittt.rosy.cam.ui.PairingScreen
import io.github.livsbittt.rosy.cam.service.StreamService
import io.github.livsbittt.rosy.cam.settings.PairingUri
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import io.github.livsbittt.rosy.cam.settings.SiteLink
import io.github.livsbittt.rosy.cam.settings.SiteLinkPrefs
import io.github.livsbittt.rosy.cam.ui.RosyTheme
import io.github.livsbittt.rosy.cam.ui.SettingsScreen
import io.github.livsbittt.rosy.cam.ui.StreamScreen
import io.github.livsbittt.rosy.cam.ui.invalidText
import io.github.livsbittt.rosy.cam.ui.rememberLan
import kotlinx.coroutines.launch
import io.github.livsbittt.rosy.cam.health.ScreenPower
import io.github.livsbittt.rosy.cam.health.ScreenCoolingPolicy
import io.github.livsbittt.rosy.cam.pairing.peer.CameraPeerViewModel
import io.github.livsbittt.rosy.cam.pairing.peer.CameraPeerState
import io.github.livsbittt.rosy.cam.ui.CameraLanScreen
import io.github.livsbittt.rosy.cam.ui.CameraPeerScreen

/**
 * Single activity: stream screen + settings screen, runtime permissions, and the
 * `rosyov://` pairing deep link (D-261 6). A deep link is only saved after the operator
 * confirms, so a stray link cannot silently redirect frames to another host.
 */
class MainActivity : ComponentActivity() {
    private val pendingPairing = mutableStateOf<PairingUri?>(null)
    private val deepLinkInvalid = mutableStateOf<String?>(null)
    private lateinit var settings: SettingsStore
    private val pairingModel: PairingViewModel by viewModels()
    private val cameraPeerModel: CameraPeerViewModel by viewModels()
    private val screenCooling = ScreenCoolingPolicy()
    private val screenResting = mutableStateOf(false)
    private lateinit var screenPower: ScreenPower

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        screenPower = ScreenPower(this)
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
    override fun onStop() {
        if (!isChangingConfigurations) cameraPeerModel.close()
        super.onStop()
    }

    private fun handlePairingIntent(intent: Intent?) {
        if (intent?.action != Intent.ACTION_VIEW) return
        val data = intent.data ?: return
        if (!data.scheme.equals(PairingUri.SCHEME, ignoreCase = true)) return
        when (val parsed = PairingUri.parse(data.toString())) {
            is PairingUri.Parsed.Valid -> {
                // The link parses, but a host name must still be a .local site name (D-391 1).
                val reason = SiteLink.entryReason(parsed.pairing)
                pendingPairing.value = parsed.pairing.takeIf { reason == null }
                deepLinkInvalid.value = reason
            }
            is PairingUri.Parsed.Invalid -> deepLinkInvalid.value = parsed.reason
        }
    }

    private fun hasCamera(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun sleepScreen(askPermission: Boolean) {
        screenResting.value = true
        screenPower.sleep(askPermission)
    }

    @Deprecated("Device-admin activation requires the platform result")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == ScreenPower.REQUEST_SCREEN_LOCK && screenPower.approved()) screenPower.sleep()
    }

    @Composable
    private fun OverheadApp() {
        val state by StreamService.state.collectAsStateWithLifecycle()
        LaunchedEffect(state.health, state.running) {
            if (state.running && screenCooling.requestSleep(state.health)) sleepScreen(false)
        }
        if (screenResting.value) {
            Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).padding(24.dp)) {
                Text("화면 보호 · 촬영과 전송은 계속됩니다", color = MaterialTheme.colorScheme.onBackground)
                Text("화면 잠금이 허용되지 않았다면 기기의 자동 꺼짐 시간에 맞춰 화면이 꺼집니다.",
                     color = MaterialTheme.colorScheme.onSurfaceVariant)
                TextButton(onClick = { screenResting.value = false; screenPower.restore() }) { Text("화면 다시 보기") }
            }
            return
        }
        val stored by settings.stored.collectAsStateWithLifecycle(initialValue = SiteLinkPrefs.Stored(null))
        val siteLink = stored.link
        val development by settings.development.collectAsStateWithLifecycle(initialValue = null)
        val pairing = siteLink?.toPairing()
        // The Wi-Fi now: "not connected" check, and the pairing-time subnet saved for diagnosis only.
        val lan = rememberLan()
        val lens by settings.lens.collectAsStateWithLifecycle(initialValue = null)
        val recognitionExposure by settings.recognitionExposure.collectAsStateWithLifecycle(initialValue = true)
        var showSettings by remember { mutableStateOf(false) }
        var showLan by remember { mutableStateOf(true) }
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

        // The attempt lives in the ViewModel, so rotation keeps the code, the poll loop and a running answer.
        val attempt by pairingModel.attempt.collectAsStateWithLifecycle()
        val peerState by cameraPeerModel.state.collectAsStateWithLifecycle()
        val rememberedPeers by cameraPeerModel.remembered.collectAsStateWithLifecycle()
        val current = attempt
        if (peerState != CameraPeerState.Idle && !state.running) {
            CameraPeerScreen(peerState, cameraPeerModel::confirmCertificate, cameraPeerModel::close, cameraPeerModel::open,
                onDone = { cameraPeerModel.close(); showLan = false }, onForget = cameraPeerModel::forget)
        } else if (current != null) {
            val session = current.session
            val pairingState by session.state.collectAsStateWithLifecycle()
            val busy by session.busy.collectAsStateWithLifecycle()
            PairingScreen(
                site = current.site,
                state = pairingState,
                busy = busy,
                onAnswer = session::answer,
                onCancel = { pairingModel.close() },
                onRetry = { session.start(current.site) },
                onClose = {
                    if (pairingState is PairingState.Paired) { showSettings = false; showLan = false }
                    pairingModel.close()
                },
            )
        } else if (showLan && !showSettings && !state.running) {
            CameraLanScreen(onSelect = { record ->
                val site = PairableSite(record.name, record.tlsHost, record.port, record.address)
                if (record.peerApproval) cameraPeerModel.open(site)
                else pairingModel.open(site, deviceLabel(), BuildConfig.VERSION_NAME)
            }, onSettings = { showSettings = true }, onCurrent = if (siteLink == null) null else ({ showLan = false }),
                remembered = rememberedPeers, onRemembered = cameraPeerModel::open)
        } else if (showSettings) {
            SettingsScreen(
                currentLink = siteLink,
                locked = state.running,
                lens = LensChoice.orDefault(lens),
                onLens = { choice -> scope.launch { settings.saveLens(choice) } },
                recognitionExposure = recognitionExposure,
                onRecognitionExposure = { on -> scope.launch { settings.saveRecognitionExposure(on) } },
                onSave = { p, siteName, fresh ->
                    // A settings edit keeps the pairing-time subnet; only a fresh pairing records the current one.
                    val subnet = if (fresh) lan?.subnet else null
                    scope.launch { settings.save(p, siteName, subnet) }
                },
                onBack = { showSettings = false },
                development = development,
                onDevelopmentImport = { bootstrap, result ->
                    scope.launch {
                        result(runCatching { settings.importDevelopment(bootstrap) }.isSuccess)
                    }
                },
                onDevelopmentRevoke = { scope.launch { settings.revokeDevelopment() } },
                onPairRequest = { record ->
                    val selected = PairableSite(record.name, record.tlsHost, record.port, record.address)
                    if (record.peerApproval) { showSettings = false; cameraPeerModel.open(selected) }
                    else pairingModel.open(selected, deviceLabel(), BuildConfig.VERSION_NAME)
                },
            )
        } else {
            StreamScreen(
                state = state,
                siteLink = siteLink,
                rejectedHost = stored.rejectedHost,
                droppedTlsHost = stored.droppedTlsHost,
                lan = lan,
                localError = localError,
                onStart = onStart,
                onStop = { StreamService.stop(this) },
                onScreenOff = { sleepScreen(true) },
                onOpenSettings = { showLan = true; showSettings = state.running },
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
                        enabled = !state.running && development == null,
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

/** The phone's model as the console's device label: printable, at most 64 characters (rosy-pair/1 request). */
private fun deviceLabel(): String =
    Build.MODEL.orEmpty().filterNot { it.code < 32 || it.code == 127 }.trim().take(64).ifBlank { "Rosy Cam" }

private const val KEY_PENDING_PAIRING = "pending_pairing"
private const val KEY_DEEP_LINK_INVALID = "deep_link_invalid"

/** `sha256/` plus 12 base64url characters: enough to compare by eye with the site's printout. */
internal const val PIN_PREVIEW = 19
