package io.github.livsbittt.rosy.cam.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.pairing.PairingSession
import io.github.livsbittt.rosy.cam.pairing.PairingState

/** Korean text for a final pairing reason. Pure, so the mapping is tested on the JVM. */
object PairingText {
    private val CERTIFICATE = setOf("leaf_san", "leaf_not_signed_by_ca", PairingSession.LEAF_CHANGED)
    private val CONFIRM = setOf("confirm_failed", "confirm_busy", "credential_mismatch", "not_delivered")

    /** The message for a [PairingState.Rejected] or [PairingState.Expired]; null for any other state. */
    fun failure(state: PairingState): Int? = when (state) {
        is PairingState.Expired -> when (state.reason) {
            "confirm_deadline" -> R.string.pairing_failed_confirm_deadline
            "unknown_request" -> R.string.pairing_failed_unknown_request
            else -> R.string.pairing_failed_expired
        }
        is PairingState.Rejected -> when {
            state.reason == "rejected" -> R.string.pairing_failed_rejected
            state.reason == "fingerprint_mismatch" -> R.string.pairing_failed_fingerprint
            state.reason in CERTIFICATE -> R.string.pairing_failed_certificate
            state.reason == "busy" -> R.string.pairing_failed_busy
            state.reason == "unreachable" -> R.string.pairing_failed_unreachable
            state.reason in CONFIRM || state.reason.startsWith("confirm_") -> R.string.pairing_failed_confirm
            // A result or reply that failed the rosy-pair/1 shape rules: nothing was stored or confirmed.
            state.reason in RESULT_REASONS -> R.string.pairing_failed_result
            else -> R.string.pairing_failed_other
        }
        else -> null
    }

    private val RESULT_REASONS = setOf(
        "not_object", "missing_field", "proto", "role", "bad_value", "bad_tls_host", "bad_ca_pem", "leaf_not_ca",
        "bad_expires_at", "bad_reply", "site_link",
    )

    /** "123456" as "123 456": easier to read aloud and type. */
    fun groupedCode(code: String): String = if (code.length == 6) code.substring(0, 3) + " " + code.substring(3) else code
}

/** The `rosy-pair/1` flow on one screen: code, wait, fingerprint check, result (D-341 3, 4). */
@Composable
fun PairingScreen(
    site: PairableSite,
    state: PairingState,
    busy: Boolean,
    onAnswer: (Boolean) -> Unit,
    onCancel: () -> Unit,
    onRetry: () -> Unit,
    onClose: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .safeDrawingPadding()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(stringResource(R.string.pairing_title), style = MaterialTheme.typography.headlineSmall)
        Text(stringResource(R.string.pairing_site, site.serviceName, site.tlsHost), style = MaterialTheme.typography.bodyMedium)

        when (state) {
            PairingState.Discover -> {
                Text(stringResource(R.string.pairing_working), style = MaterialTheme.typography.bodyLarge)
                OutlinedButton(onClick = onCancel) { Text(stringResource(R.string.pairing_cancel)) }
            }
            is PairingState.Requested, is PairingState.AwaitingApproval -> {
                val code = if (state is PairingState.Requested) state.code else (state as PairingState.AwaitingApproval).code
                Text(stringResource(R.string.pairing_code_intro), style = MaterialTheme.typography.bodyLarge)
                Text(
                    PairingText.groupedCode(code),
                    style = MaterialTheme.typography.displayLarge,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.semantics { contentDescription = code.toList().joinToString(" ") },
                )
                Text(stringResource(R.string.pairing_waiting), style = MaterialTheme.typography.bodyMedium)
                OutlinedButton(onClick = onCancel) { Text(stringResource(R.string.pairing_cancel)) }
            }
            is PairingState.ConfirmFingerprint -> {
                Text(stringResource(R.string.pairing_fp_title), style = MaterialTheme.typography.titleMedium)
                Text(stringResource(R.string.pairing_fp_intro), style = MaterialTheme.typography.bodyLarge)
                Text(stringResource(R.string.pairing_fp_label), style = MaterialTheme.typography.labelLarge)
                Text(
                    state.fingerprint,
                    style = MaterialTheme.typography.headlineMedium,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    stringResource(R.string.pairing_credential, state.credentialId),
                    style = MaterialTheme.typography.bodyLarge,
                    fontFamily = FontFamily.Monospace,
                )
                Text(stringResource(R.string.pairing_fp_site, state.siteName, state.sourceId), style = MaterialTheme.typography.bodyMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedButton(enabled = !busy, onClick = { onAnswer(false) }) { Text(stringResource(R.string.pairing_fp_mismatch)) }
                    Button(enabled = !busy, onClick = { onAnswer(true) }) { Text(stringResource(R.string.pairing_fp_match)) }
                }
            }
            is PairingState.Paired -> {
                Text(
                    stringResource(R.string.pairing_paired, state.link.siteName ?: site.serviceName, state.link.source),
                    color = RosyColors.StatusOk,
                    style = MaterialTheme.typography.bodyLarge,
                )
                Button(onClick = onClose) { Text(stringResource(R.string.pairing_done)) }
            }
            is PairingState.Rejected, is PairingState.Expired -> {
                val reason = if (state is PairingState.Rejected) state.reason else (state as PairingState.Expired).reason
                val message = PairingText.failure(state) ?: R.string.pairing_failed_other
                CritMessage(stringResource(message, reason))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedButton(onClick = onClose) { Text(stringResource(R.string.pairing_close)) }
                    Button(onClick = onRetry) { Text(stringResource(R.string.pairing_retry)) }
                }
            }
        }
        if (busy && state !is PairingState.Discover) {
            Text(stringResource(R.string.pairing_working), style = MaterialTheme.typography.bodySmall)
        }
    }
}
