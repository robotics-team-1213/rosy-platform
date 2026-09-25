package io.github.livsbittt.rosy.overhead.ui

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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.livsbittt.rosy.overhead.R
import io.github.livsbittt.rosy.overhead.settings.PairingUri

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
    var invalid by remember { mutableStateOf<String?>(null) }
    var saved by remember { mutableStateOf(false) }

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
        if (locked) {
            Text(stringResource(R.string.settings_locked), color = MaterialTheme.colorScheme.error)
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

        invalid?.let { Text(invalidText(it), color = MaterialTheme.colorScheme.error) }
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
                        onSave(PairingUri(trimmedHost, portNumber, token, source.trim()))
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
        else -> R.string.invalid_source
    },
)
