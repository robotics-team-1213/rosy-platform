package io.github.livsbittt.rosy.cam.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.background
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.livsbittt.rosy.cam.PIN_PREVIEW
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.camera.LensCandidate
import io.github.livsbittt.rosy.cam.camera.LensChoice
import io.github.livsbittt.rosy.cam.camera.LensProbe
import io.github.livsbittt.rosy.cam.camera.LensSelector
import io.github.livsbittt.rosy.cam.settings.PairingUri
import io.github.livsbittt.rosy.cam.settings.OverheadServerDiscovery
import io.github.livsbittt.rosy.cam.settings.OverheadServiceRecord
import io.github.livsbittt.rosy.cam.settings.RobotCoreServiceRecord
import io.github.livsbittt.rosy.cam.settings.SiteLink
import io.github.livsbittt.rosy.cam.settings.DevelopmentBootstrap
import io.github.livsbittt.rosy.cam.settings.LinkPolicy

/** Manual pairing entry, validated with the same rules as the rosyov:// deep link. */
@Composable
fun SettingsScreen(
    currentLink: SiteLink?,
    locked: Boolean,
    lens: LensChoice,
    onLens: (LensChoice) -> Unit,
    /**
     * The pairing; when it came from the mDNS list, that service's name (`site_name`); and whether it is a fresh
     * pairing (a link applied or a receiver picked) rather than an edit of the saved one. Only a fresh pairing
     * records the Wi-Fi subnet for diagnosis (review m6).
     */
    onSave: (PairingUri, String?, Boolean) -> Unit,
    onBack: () -> Unit,
    /** D-341: a receiver that advertises `pair=rosy-pair/1` was picked for a console-approved request. */
    onPairRequest: (OverheadServiceRecord) -> Unit = {},
    development: LinkPolicy? = null,
    onDevelopmentImport: (DevelopmentBootstrap, (Boolean) -> Unit) -> Unit = { _, result -> result(false) },
    onDevelopmentRevoke: () -> Unit = {},
) {
    val current = remember(currentLink) { currentLink?.toPairing() }
    var siteName by remember(currentLink) { mutableStateOf(currentLink?.siteName) }
    var freshPairing by remember(currentLink) { mutableStateOf(false) }
    var link by remember { mutableStateOf("") }
    var importingDevelopment by remember { mutableStateOf(false) }
    var host by remember(current) { mutableStateOf(current?.host ?: "") }
    var port by remember(current) { mutableStateOf(current?.port?.toString() ?: "") }
    var token by remember(current) { mutableStateOf(current?.token ?: "") }
    var source by remember(current) { mutableStateOf(current?.source ?: "overhead-1") }
    var secure by remember(current) { mutableStateOf(current?.secure ?: false) }
    // Only a rosyov:// link sets the pin; it is not typed by hand and is dropped when TLS is unchecked.
    var pin by remember(current) { mutableStateOf(current?.pin) }
    var pinDropped by remember(current) { mutableStateOf(false) }
    var invalid by remember { mutableStateOf<String?>(null) }
    var saved by remember { mutableStateOf(false) }
    var overheadServices by remember { mutableStateOf(emptyList<OverheadServiceRecord>()) }
    var robotServices by remember { mutableStateOf(emptyList<RobotCoreServiceRecord>()) }
    var scanning by remember { mutableStateOf(false) }
    var wifiConnected by remember { mutableStateOf(false) }
    var scanGeneration by remember { mutableStateOf(0) }
    val context = LocalContext.current
    val discovery = remember(context, scanGeneration, locked) {
        OverheadServerDiscovery(context) { overhead, robots, active, onWifi ->
            overheadServices = overhead
            robotServices = robots
            scanning = active
            wifiConnected = onWifi
        }
    }
    // No scan while the camera runs: the stream's own re-discovery needs the one NSD resolve slot on
    // Android < 14, and settings are read-only then anyway (review m8).
    LaunchedEffect(discovery) { if (!locked) discovery.start() }
    var backCameras by remember { mutableStateOf<List<LensCandidate>?>(null) }
    LaunchedEffect(Unit) {
        backCameras = try {
            LensProbe.backCameras(context)
        } catch (e: Exception) {
            emptyList()
        }
    }
    DisposableEffect(discovery) { onDispose { discovery.stop() } }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .safeDrawingPadding()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(stringResource(R.string.settings_title), style = MaterialTheme.typography.headlineSmall)
        if (development != null) {
            Text(stringResource(R.string.settings_development_active, development.siteName, development.expiresAt.toString()))
            OutlinedButton(onClick = onDevelopmentRevoke, enabled = !locked, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.settings_development_revoke))
            }
        }
        // First line while the camera runs, so the disabled Save button is explained before it is seen.
        if (locked) {
            Text(stringResource(R.string.settings_locked), style = MaterialTheme.typography.bodyLarge)
        }
        LensSection(lens, backCameras, running = locked, onLens = onLens)
        Text(stringResource(R.string.settings_mdns_intro), style = MaterialTheme.typography.bodyMedium)
        OutlinedButton(
            enabled = !locked,
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                discovery.stop()
                overheadServices = emptyList()
                robotServices = emptyList()
                scanGeneration += 1
            },
        ) {
            Text(
                stringResource(
                    if (scanning || overheadServices.isNotEmpty() || robotServices.isNotEmpty()) {
                        R.string.settings_mdns_rescan
                    } else {
                        R.string.settings_mdns_scan
                    },
                ),
            )
        }
        if (scanning) Text(stringResource(R.string.settings_mdns_scanning))
        if (locked) {
            Text(stringResource(R.string.settings_mdns_paused), style = MaterialTheme.typography.bodySmall)
        } else if (!wifiConnected) {
            Text(stringResource(R.string.settings_mdns_wifi_required), color = RosyColors.StatusWarn)
        } else {
            Text(stringResource(R.string.settings_mdns_overhead_heading), style = MaterialTheme.typography.titleSmall)
            if (overheadServices.isEmpty()) {
                if (!scanning) {
                    Text(stringResource(R.string.settings_mdns_overhead_empty), style = MaterialTheme.typography.bodySmall)
                }
            } else {
                overheadServices.forEach { service ->
                    OutlinedButton(
                        onClick = {
                            host = service.tlsHost
                            port = service.port.toString()
                            secure = true
                            siteName = service.name
                            freshPairing = true
                            invalid = null
                            saved = false
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.settings_mdns_overhead, service.name, service.tlsHost, service.port))
                    }
                }
            }

            // D-341 2, 14: only a TLS receiver advertising pair=rosy-pair/1 (and resolved to an address) gets a button.
            Text(stringResource(R.string.pairing_request), style = MaterialTheme.typography.titleSmall)
            Text(stringResource(R.string.pairing_request_intro), style = MaterialTheme.typography.bodySmall)
            val pairable = overheadServices.filter { it.pairable && it.address != null }
            if (pairable.isEmpty()) {
                if (!scanning) {
                    Text(stringResource(R.string.pairing_request_none), style = MaterialTheme.typography.bodySmall)
                }
            } else {
                pairable.forEach { service ->
                    Button(onClick = { onPairRequest(service) }, enabled = development == null, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(R.string.pairing_request_site, service.name))
                    }
                }
            }

            Text(stringResource(R.string.settings_mdns_robot_heading), style = MaterialTheme.typography.titleSmall)
            if (robotServices.isEmpty()) {
                if (!scanning) {
                    Text(stringResource(R.string.settings_mdns_robot_empty), style = MaterialTheme.typography.bodySmall)
                }
            } else {
                robotServices.forEach { service ->
                    Text(
                        stringResource(R.string.settings_mdns_robot, service.name, service.host, service.port),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }

        OutlinedTextField(
            value = link,
            onValueChange = { link = it },
            label = { Text(stringResource(R.string.settings_link)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedButton(
            onClick = {
                if (link.trimStart().startsWith("{")) {
                    runCatching { DevelopmentBootstrap.parse(link) }
                        .onSuccess { bootstrap ->
                            importingDevelopment = true
                            onDevelopmentImport(bootstrap) { success ->
                                importingDevelopment = false
                                if (success) { link = ""; invalid = null } else invalid = "bootstrap"
                            }
                        }
                        .onFailure { invalid = "bootstrap" }
                    return@OutlinedButton
                }
                when (val parsed = PairingUri.parse(link)) {
                    is PairingUri.Parsed.Valid -> {
                        if (parsed.pairing.host != host) siteName = null
                        host = parsed.pairing.host
                        port = parsed.pairing.port.toString()
                        token = parsed.pairing.token
                        source = parsed.pairing.source
                        secure = parsed.pairing.secure
                        pin = parsed.pairing.pin
                        pinDropped = false
                        freshPairing = true
                        invalid = null
                    }
                    is PairingUri.Parsed.Invalid -> invalid = parsed.reason
                }
                saved = false
            },
            enabled = link.isNotBlank() && !locked && development == null && !importingDevelopment,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(stringResource(R.string.settings_link_apply))
        }

        Field(host, { host = it; siteName = null; saved = false }, R.string.settings_host, invalid == "host" || invalid == "tls_host")
        // D-391 1: the saved IP is only the labelled fallback; the name is looked up through mDNS on each connect.
        currentLink?.manualHost?.let { manual ->
            Text(
                stringResource(if (currentLink.tlsHost == null) R.string.settings_manual_only else R.string.settings_manual_host, manual),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Field(port, { port = it; saved = false }, R.string.settings_port, invalid == "port", KeyboardType.Number)
        OutlinedTextField(
            value = token,
            onValueChange = { token = it; saved = false },
            label = { Text(stringResource(R.string.settings_token)) },
            isError = invalid == "token",
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth(),
        )
        Field(source, { source = it; saved = false }, R.string.settings_source, invalid == "source")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Checkbox(
                checked = secure,
                onCheckedChange = {
                    secure = it
                    if (!it && pin != null) {
                        pin = null
                        pinDropped = true
                    }
                    saved = false
                },
            )
            Text(stringResource(R.string.settings_tls))
        }
        if (secure) {
            Text(
                pin?.let { stringResource(R.string.settings_pin, it.take(PIN_PREVIEW)) }
                    ?: stringResource(R.string.settings_pin_none),
                style = MaterialTheme.typography.bodySmall,
            )
        }
        if (pinDropped && pin == null) {
            Text(stringResource(R.string.settings_pin_dropped), color = RosyColors.StatusWarn)
        }

        invalid?.let { CritMessage(invalidText(it)) }
        if (saved) Text(stringResource(R.string.settings_saved), color = MaterialTheme.colorScheme.primary)

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(onClick = onBack, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.settings_back)) }
            Button(
                enabled = !locked && development == null,
                modifier = Modifier.weight(1f),
                onClick = {
                    val trimmedHost = host.trim()
                    val portNumber = port.trim().toIntOrNull() ?: -1
                    // Field rules first, then the site-link rules (D-391 1: a name must be <label>.local).
                    val reason = PairingUri.validate(trimmedHost, portNumber, token, source.trim(), secure, pin)
                        ?: SiteLink.entryReason(PairingUri(trimmedHost, portNumber, token, source.trim(), secure, pin))
                    invalid = reason
                    if (reason == null) {
                        onSave(PairingUri(trimmedHost, portNumber, token, source.trim(), secure, pin), siteName, freshPairing)
                        saved = true
                    }
                },
            ) {
                Text(stringResource(R.string.settings_save))
            }
        }
    }
}

/** 화각: wide/standard radio, the lens each one binds, and the no-ultra-wide fallback note. */
@Composable
private fun LensSection(
    lens: LensChoice,
    backCameras: List<LensCandidate>?,
    running: Boolean,
    onLens: (LensChoice) -> Unit,
) {
    val res = LocalContext.current.resources
    Text(stringResource(R.string.settings_lens_heading), style = MaterialTheme.typography.titleSmall)
    Column(Modifier.selectableGroup()) {
        for (choice in LensChoice.entries) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .selectable(selected = lens == choice, role = Role.RadioButton, onClick = { onLens(choice) })
                    .padding(vertical = 4.dp),
            ) {
                RadioButton(selected = lens == choice, onClick = null)
                Text(
                    stringResource(if (choice == LensChoice.WIDE) R.string.settings_lens_wide else R.string.settings_lens_standard),
                    modifier = Modifier.padding(start = 8.dp),
                )
            }
        }
    }
    backCameras?.let { LensSelector.pick(it, lens) }?.let { pick ->
        LensText.line(res, pick)?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
    }
    Text(
        stringResource(if (running) R.string.settings_lens_running else R.string.settings_lens_intro),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun Field(
    value: String,
    onChange: (String) -> Unit,
    label: Int,
    isError: Boolean,
    keyboardType: KeyboardType = KeyboardType.Text,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(stringResource(label)) },
        isError = isError,
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        modifier = Modifier.fillMaxWidth(),
    )
}

/** Korean text for a PairingUri invalid reason. */
@Composable
fun invalidText(reason: String): String = stringResource(
    when (reason) {
        "scheme" -> R.string.invalid_scheme
        "host" -> R.string.invalid_host
        "port" -> R.string.invalid_port
        "token" -> R.string.invalid_token
        "tls" -> R.string.invalid_tls
        "pin" -> R.string.invalid_pin
        "tls_host" -> R.string.invalid_tls_host
        "bootstrap" -> R.string.invalid_development_bootstrap
        else -> R.string.invalid_source
    },
)
