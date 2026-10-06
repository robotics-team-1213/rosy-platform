package io.github.livsbittt.rosy.cam.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.pairing.PairingClient
import io.github.livsbittt.rosy.cam.pairing.PairingSession
import io.github.livsbittt.rosy.cam.pairing.PairingState

/** Korean text for a final pairing reason. Pure, so the mapping is tested on the JVM. */
object PairingText {
    private val CERTIFICATE = setOf("leaf_san", "leaf_not_signed_by_ca", PairingSession.LEAF_CHANGED)

    /** The credential a failed confirm may have left active on the server; null for any other end. */
    fun unsettledCredential(state: PairingState): String? = when (state) {
        is PairingState.Rejected -> state.credentialId
        is PairingState.Expired -> state.credentialId
        else -> null
    }

    /** The message for a [PairingState.Rejected] or [PairingState.Expired]; null for any other state. */
    fun failure(state: PairingState): Int? {
        // Confirm was sent, then refused or unanswered: the operator revokes the credential first.
        if (unsettledCredential(state) != null) {
            return if ((state as? PairingState.Rejected)?.reason == PairingClient.CONFIRM_UNANSWERED) {
                R.string.pairing_failed_unanswered
            } else {
                R.string.pairing_failed_revoke
            }
        }
        return when (state) {
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
                // A result or reply that failed the rosy-pair/1 shape rules: nothing was stored or confirmed.
                state.reason in RESULT_REASONS -> R.string.pairing_failed_result
                else -> R.string.pairing_failed_other
            }
            else -> null
        }
    }

    /** The format argument of [failure]'s message: the credential id for the unanswered case, else the reason. */
    fun failureArg(state: PairingState): String = when (state) {
        is PairingState.Rejected -> if (state.reason == PairingClient.CONFIRM_UNANSWERED) state.credentialId.orEmpty() else state.reason
        is PairingState.Expired -> state.reason
        else -> ""
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
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .safeDrawingPadding(),
    ) {
        Column(
            modifier = Modifier
                .widthIn(max = 560.dp)
                .fillMaxWidth()
                .align(Alignment.TopCenter)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(stringResource(R.string.pairing_title), style = MaterialTheme.typography.headlineSmall)
            Text(stringResource(R.string.pairing_site, site.serviceName, site.tlsHost), style = MaterialTheme.typography.bodyMedium)

            when (state) {
                PairingState.Discover -> {
                    Text(stringResource(R.string.pairing_working), style = MaterialTheme.typography.bodyLarge)
                    OutlinedButton(onClick = onCancel, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pairing_cancel)) }
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
                    OutlinedButton(onClick = onCancel, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pairing_cancel)) }
                }
                is PairingState.ConfirmFingerprint -> {
                    Text(stringResource(R.string.pairing_fp_title), style = MaterialTheme.typography.titleMedium)
                    Text(stringResource(R.string.pairing_fp_intro), style = MaterialTheme.typography.bodyLarge)
                    Text(stringResource(R.string.pairing_fp_label), style = MaterialTheme.typography.labelLarge)
                    Text(
                        state.fingerprint.replace("-", "-\u200B"),
                        style = MaterialTheme.typography.headlineMedium,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.semantics { contentDescription = state.fingerprint },
                    )
                    Text(
                        stringResource(R.string.pairing_credential, state.credentialId),
                        style = MaterialTheme.typography.bodyLarge,
                        fontFamily = FontFamily.Monospace,
                    )
                    // No site-supplied free text before the fingerprint is confirmed: source_id is pattern-checked.
                    Text(stringResource(R.string.pairing_fp_source, state.sourceId), style = MaterialTheme.typography.bodyMedium)
                    Column(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        OutlinedButton(enabled = !busy, onClick = { onAnswer(false) }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pairing_fp_mismatch)) }
                        Button(enabled = !busy, onClick = { onAnswer(true) }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pairing_fp_match)) }
                    }
                }
                is PairingState.Paired -> {
                    Text(
                        stringResource(R.string.pairing_paired, state.link.siteName ?: site.serviceName, state.link.source),
                        color = RosyColors.StatusOk,
                        style = MaterialTheme.typography.bodyLarge,
                    )
                    Button(onClick = onClose, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pairing_done)) }
                }
                is PairingState.Rejected, is PairingState.Expired -> {
                    val message = PairingText.failure(state) ?: R.string.pairing_failed_other
                    CritMessage(stringResource(message, PairingText.failureArg(state)))
                    PairingText.unsettledCredential(state)?.let { id ->
                        Text(stringResource(R.string.pairing_credential, id), fontFamily = FontFamily.Monospace)
                    }
                    Column(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        OutlinedButton(onClick = onClose, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pairing_close)) }
                        Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pairing_retry)) }
                    }
                }
            }
            if (busy && state !is PairingState.Discover) {
                Text(stringResource(R.string.pairing_working), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
