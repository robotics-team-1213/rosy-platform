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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.settings.PairingUri
import io.github.livsbittt.rosy.cam.settings.OverheadServerDiscovery
import io.github.livsbittt.rosy.cam.settings.OverheadServiceRecord
import io.github.livsbittt.rosy.cam.settings.RobotCoreServiceRecord

/** Manual pairing entry, validated with the same rules as the rosyov:// deep link. */
@Composable
fun SettingsScreen(
    current: PairingUri?,
    locked: Boolean,
    onSave: (PairingUri) -> Unit,
    onBack: () -> Unit,
) {
    var link by remember { mutableStateOf("") }
    var host by remember(current) { mutableStateOf(current?.host ?: "") }
    var port by remember(current) { mutableStateOf(current?.port?.toString() ?: "") }
    var token by remember(current) { mutableStateOf(current?.token ?: "") }
    var source by remember(current) { mutableStateOf(current?.source ?: "overhead-1") }
    var secure by remember(current) { mutableStateOf(current?.secure ?: false) }
    var invalid by remember { mutableStateOf<String?>(null) }
    var saved by remember { mutableStateOf(false) }
    var overheadServices by remember { mutableStateOf(emptyList<OverheadServiceRecord>()) }
    var robotServices by remember { mutableStateOf(emptyList<RobotCoreServiceRecord>()) }
    var scanning by remember { mutableStateOf(false) }
    var wifiConnected by remember { mutableStateOf(false) }
    var scanGeneration by remember { mutableStateOf(0) }
    val context = LocalContext.current
    val discovery = remember(context, scanGeneration) {
        OverheadServerDiscovery(context) { overhead, robots, active, onWifi ->
            overheadServices = overhead
            robotServices = robots
            scanning = active
            wifiConnected = onWifi
        }
    }
    LaunchedEffect(discovery) { discovery.start() }
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
        // First line while the camera runs, so the disabled Save button is explained before it is seen.
        if (locked) {
            Text(stringResource(R.string.settings_locked), style = MaterialTheme.typography.bodyLarge)
        }
        Text(stringResource(R.string.settings_mdns_intro), style = MaterialTheme.typography.bodyMedium)
        OutlinedButton(
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
        if (!wifiConnected) {
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
                            invalid = null
                            saved = false
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(stringResource(R.string.settings_mdns_overhead, service.name, service.tlsHost, service.port))
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
                when (val parsed = PairingUri.parse(link)) {
                    is PairingUri.Parsed.Valid -> {
                        host = parsed.pairing.host
                        port = parsed.pairing.port.toString()
                        token = parsed.pairing.token
                        source = parsed.pairing.source
                        secure = parsed.pairing.secure
                        invalid = null
                    }
                    is PairingUri.Parsed.Invalid -> invalid = parsed.reason
                }
                saved = false
            },
            enabled = link.isNotBlank(),
        ) {
            Text(stringResource(R.string.settings_link_apply))
        }

        Field(host, { host = it; saved = false }, R.string.settings_host, invalid == "host")
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
            Checkbox(checked = secure, onCheckedChange = { secure = it; saved = false })
            Text(stringResource(R.string.settings_tls))
        }

        invalid?.let { CritMessage(invalidText(it)) }
        if (saved) Text(stringResource(R.string.settings_saved), color = MaterialTheme.colorScheme.primary)

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedButton(onClick = onBack) { Text(stringResource(R.string.settings_back)) }
            Button(
                enabled = !locked,
                onClick = {
                    val trimmedHost = host.trim()
                    val portNumber = port.trim().toIntOrNull() ?: -1
                    val reason = PairingUri.validate(trimmedHost, portNumber, token, source.trim())
                    invalid = reason
                    if (reason == null) {
                        onSave(PairingUri(trimmedHost, portNumber, token, source.trim(), secure))
                        saved = true
                    }
                },
            ) {
                Text(stringResource(R.string.settings_save))
            }
        }
    }
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
        else -> R.string.invalid_source
    },
)
