package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.settings.SiteLink
import io.github.livsbittt.rosy.cam.settings.SiteLinkRecord
import java.security.InvalidAlgorithmParameterException
import java.security.cert.CertPathValidator
import java.security.cert.CertPathValidatorException
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.PKIXParameters
import java.security.cert.TrustAnchor
import java.security.cert.X509Certificate
import java.time.Instant
import java.time.format.DateTimeParseException
import java.util.Locale

/** A discovery record that passed [Pairing.pairable]: where the pairing request goes (D-341 2, 14). */
data class PairableSite(val serviceName: String, val tlsHost: String, val port: Int)

/** The site refused a pairing call with this HTTP [status], S2 error [code] and `Retry-After` seconds. */
class PairingRefused(val status: Int, val code: String? = null, val retryAfterS: Long? = null) :
    Exception("pairing refused: HTTP $status ${code.orEmpty()}")

/** Where a paired link goes. [discard] undoes [save] (restores what was there before) when confirm fails. */
interface PairingLinkStore {
    fun save(link: SiteLink)

    fun discard(link: SiteLink)
}

/**
 * The network side of [PairingClient]; Phase 2 implements it over the S2 routes `/api/fleet/pairing/v1/...`.
 * Bodies are raw JSON bytes. A refusal throws [PairingRefused]; an I/O failure throws as is and leaves the
 * client's state unchanged, so the caller may retry the same step.
 */
interface PairingTransport {
    /**
     * First contact (D-341 3): a TLS handshake to [site] that records, without validating, the leaf certificate
     * the site served. Later calls of this pairing trust only that leaf (D-341 8).
     */
    fun firstContactLeaf(site: PairableSite): X509Certificate

    fun request(site: PairableSite, body: ByteArray): ByteArray

    fun reveal(site: PairableSite, requestId: String, pollSecret: String, body: ByteArray): ByteArray

    fun poll(site: PairableSite, requestId: String, pollSecret: String): ByteArray

    fun confirm(site: PairableSite, requestId: String, pollSecret: String, body: ByteArray): ByteArray
}

/** Client flow states. None of them holds a secret (nonce, poll secret, token), so they are safe to log. */
sealed interface PairingState {
    data object Discover : PairingState

    /** The request is in and the nonce revealed; the phone shows [code] for the operator to type. */
    data class Requested(val site: PairableSite, val requestId: String, val code: String, val expiresAt: String) :
        PairingState

    /** Polling; [code] stays on screen. [serverState] is `pending` or `revealed`. */
    data class AwaitingApproval(
        val site: PairableSite,
        val requestId: String,
        val code: String,
        val expiresAt: String,
        val serverState: String,
    ) : PairingState

    /**
     * Approved and received, nothing stored yet (D-341 4). The installer compares [fingerprint] and
     * [credentialId] with the console's approval screen.
     */
    data class ConfirmFingerprint(
        val site: PairableSite,
        val siteName: String,
        val sourceId: String,
        val fingerprint: String,
        val credentialId: String,
        val credentialExpiresAt: String,
    ) : PairingState

    /** Stored and confirmed; [link] is what was saved. */
    data class Paired(val link: SiteLink) : PairingState

    data class Rejected(val reason: String) : PairingState

    data class Expired(val reason: String) : PairingState
}

/**
 * The phone side of `rosy-pair/1` as a step-driven state machine (D-341 1–4, 8, 9). Pure Kotlin; the caller
 * drives [start], [poll] (at most every 2 s, S2 `POLL_TOO_FAST`) and [answerFingerprint] from the UI.
 *
 * [store] saves the link before `confirm` is sent, the order D-341 4 sets, and discards it again when the
 * confirm fails (refused, wrong reply or I/O error): an unconfirmed credential is never activated by the server.
 * A confirm whose reply was lost after the server activated it leaves an active credential the phone does
 * not keep; the operator revokes it (S2 refuses a second approval for that source until then).
 */
class PairingClient(
    private val transport: PairingTransport,
    private val deviceLabel: String,
    private val appVersion: String,
    private val store: PairingLinkStore,
    private val newSecret: () -> String = Pairing::newSecret,
    private val now: () -> Instant = Instant::now,
) {
    var state: PairingState = PairingState.Discover
        private set

    /** Retry-After of the last 429 (seconds), null when the last call was not rate limited. */
    var retryAfterS: Long? = null
        private set

    // Secrets and the first-contact leaf live here, never in [state].
    private var leaf: X509Certificate? = null
    private var pollSecret: String? = null
    private var result: PairingResult? = null
    private var confirmBy: Instant? = null

    /** Discover -> Requested: record the leaf, request with commits only, reveal, compute the code. */
    fun start(site: PairableSite): PairingState {
        check(state == PairingState.Discover || state.isFinal()) { "pairing already in progress: $state" }
        reset()
        val seen = transport.firstContactLeaf(site)
        // D-341 3: a served leaf without the advertised tls_host stops before anything is sent.
        if (!LeafBinding.namesHost(seen, site.tlsHost)) return finish(PairingState.Rejected("leaf_san"))
        val clientNonce = newSecret()
        val secret = newSecret()
        val request = PairingRequest(deviceLabel, appVersion, Pairing.commit(clientNonce), Pairing.sha256Text(secret))
        val body = request.toJson()
        PairingRequest.validate(body)?.let { return finish(PairingState.Rejected("request_$it")) }

        val parsed = when (val reply = refusing { PairingCreated.parse(transport.request(site, body)) }) {
            is Outcome.Done -> reply.value
            is Outcome.Stop -> return finish(startStop(reply.state))
        }
        val created = (parsed as? Parsed.Valid)?.value ?: return finish(PairingState.Rejected("bad_reply"))
        val revealed = refusing { transport.reveal(site, created.requestId, secret, PairingReveal(clientNonce).toJson()) }
        when (revealed) {
            is Outcome.Stop -> return finish(startStop(revealed.state))
            is Outcome.Done -> if (PairingJson.readObject(revealed.value)?.opt("state") != "revealed") {
                return finish(PairingState.Rejected("bad_reply"))
            }
        }

        leaf = seen
        pollSecret = secret
        requestId = created.requestId
        val code = Pairing.confirmationCode(
            Pairing.ROLE, created.requestId, Pairing.derSha256(seen.encoded), clientNonce, created.serverNonce,
        )
        state = PairingState.Requested(site, created.requestId, code, created.expiresAt)
        return state
    }

    /** A 429 while starting is not a retry of the same step: the site is busy, ask again later. */
    private fun startStop(stop: PairingState): PairingState = if (stop === RETRY) PairingState.Rejected("busy") else stop

    /** One poll: Requested/AwaitingApproval -> AwaitingApproval, ConfirmFingerprint, Rejected or Expired. */
    fun poll(): PairingState {
        val (site, requestId, code, expiresAt) = when (val s = state) {
            is PairingState.Requested -> Waiting(s.site, s.requestId, s.code, s.expiresAt)
            is PairingState.AwaitingApproval -> Waiting(s.site, s.requestId, s.code, s.expiresAt)
            else -> throw IllegalStateException("nothing to poll in $s")
        }
        if (!now().isBefore(instant(expiresAt))) return finish(PairingState.Expired("timeout"))
        val raw = when (val reply = refusing { transport.poll(site, requestId, pollSecret!!) }) {
            is Outcome.Done -> reply.value
            is Outcome.Stop -> return if (reply.state === RETRY) state else finish(reply.state)
        }
        val parsed = when (val reply = PollReply.parse(raw)) {
            is Parsed.Valid -> reply.value
            is Parsed.Invalid -> return finish(PairingState.Rejected(reply.reason))
        }
        return when (parsed) {
            is PollReply.Waiting -> PairingState.AwaitingApproval(site, requestId, code, expiresAt, parsed.state).also { state = it }
            is PollReply.Closed ->
                finish(if (parsed.state == "expired") PairingState.Expired("expired") else PairingState.Rejected("rejected"))
            is PollReply.Approved -> received(site, parsed.result)
        }
    }

    /** ConfirmFingerprint -> Paired (save, then confirm) or Rejected/Expired. [matches] is the installer's answer. */
    fun answerFingerprint(matches: Boolean): PairingState {
        val shown = state as? PairingState.ConfirmFingerprint ?: throw IllegalStateException("no fingerprint to confirm in $state")
        val id = requestId ?: error("no request")
        if (!matches) return finish(PairingState.Rejected("fingerprint_mismatch"))
        if (!now().isBefore(confirmBy)) return finish(PairingState.Expired("confirm_deadline"))
        val link = siteLink(shown.site, result!!) ?: return finish(PairingState.Rejected("site_link"))
        store.save(link)
        val confirm = PairingConfirm(shown.credentialId)
        val outcome = try {
            refusing { transport.confirm(shown.site, id, pollSecret!!, confirm.toJson()) }
        } catch (e: Exception) {
            // An unconfirmed credential is never activated: keep nothing of it (S2 revokes it after 120 s).
            store.discard(link)
            finish(PairingState.Rejected("confirm_failed"))
            throw e
        }
        val failed: PairingState? = when (outcome) {
            is Outcome.Stop -> if (outcome.state === RETRY) PairingState.Rejected("confirm_busy") else outcome.state
            is Outcome.Done -> confirm.replyReason(outcome.value)?.let { PairingState.Rejected("confirm_$it") }
        }
        if (failed != null) {
            store.discard(link)
            return finish(failed)
        }
        return finish(PairingState.Paired(link))
    }

    /** Drops the request locally (the server expires it on its own); back to Discover. */
    fun cancel() {
        reset()
        state = PairingState.Discover
    }

    private var requestId: String? = null

    private fun received(site: PairableSite, delivered: PairingResult): PairingState {
        val ca = SiteLinkRecord.caCertificates(delivered.siteCaPem)?.firstOrNull()
            ?: return finish(PairingState.Rejected("bad_ca_pem"))
        // D-341 9: the leaf seen on first contact must chain to the delivered CA and name the delivered tls_host.
        LeafBinding.reason(leaf!!, ca, delivered.tlsHost)?.let { return finish(PairingState.Rejected(it)) }
        if (siteLink(site, delivered) == null) return finish(PairingState.Rejected("site_link"))
        result = delivered
        // S2 CONFIRM_DEADLINE_S: the approval is revoked 120 s after it was given; the phone keeps a local bound.
        confirmBy = now().plusSeconds(CONFIRM_WITHIN_S)
        state = PairingState.ConfirmFingerprint(
            site, delivered.siteName, delivered.sourceId, Pairing.siteFingerprint(ca.encoded), delivered.credentialId,
            delivered.expiresAt,
        )
        return state
    }

    /**
     * The stored D-391 shape: the result as a site-link record (port from the discovery record, the result
     * carries none) through [SiteLinkRecord.toSiteLink], so the token is kept exactly as a pasted link's token
     * and the pin is the first CA's. Null unless [SiteLink.validate] accepts it.
     */
    private fun siteLink(site: PairableSite, r: PairingResult): SiteLink? {
        val record = mapOf(
            "site_name" to r.siteName, "tls_host" to r.tlsHost, "port" to site.port, "ca_pem" to r.siteCaPem,
            "role" to Pairing.ROLE, "credential_id" to r.credentialId, "expires_at" to r.expiresAt,
            "credential" to r.token,
        )
        return SiteLinkRecord.toSiteLink(record, token = r.token, source = r.sourceId)?.takeIf { SiteLink.validate(it) == null }
    }

    private fun finish(final: PairingState): PairingState {
        reset()
        state = final
        return final
    }

    private fun reset() {
        leaf = null
        pollSecret = null
        result = null
        confirmBy = null
        requestId = null
    }

    private fun PairingState.isFinal(): Boolean =
        this is PairingState.Paired || this is PairingState.Rejected || this is PairingState.Expired

    private data class Waiting(val site: PairableSite, val requestId: String, val code: String, val expiresAt: String)

    private sealed interface Outcome<out T> {
        data class Done<T>(val value: T) : Outcome<T>
        data class Stop(val state: PairingState) : Outcome<Nothing>
    }

    /**
     * S2 refusals as states: 404 (Fleet restarted and forgot the request, D-341 8) and 410 end as Expired,
     * 429 means "same step later" ([retryAfterS]), 401 is a poll-secret mismatch. Any other refusal is Rejected
     * with the S2 error code in lower case (`commit_mismatch`, `pairing_request_invalid`…) or `refused_<status>`.
     */
    private inline fun <T> refusing(call: () -> T): Outcome<T> = try {
        retryAfterS = null
        Outcome.Done(call())
    } catch (e: PairingRefused) {
        Outcome.Stop(
            when (e.status) {
                404 -> PairingState.Expired("unknown_request")
                410 -> PairingState.Expired("gone")
                429 -> RETRY.also { retryAfterS = e.retryAfterS }
                401 -> PairingState.Rejected("poll_secret")
                else -> PairingState.Rejected(e.code?.lowercase(Locale.ROOT) ?: "refused_${e.status}")
            },
        )
    }

    private fun instant(text: String): Instant = try {
        Instant.parse(text)
    } catch (e: DateTimeParseException) {
        Instant.MIN
    }

    companion object {
        const val CONFIRM_WITHIN_S = 120L

        /** Marker for "try the same step again later" (HTTP 429); never stored as [state]. */
        private val RETRY = PairingState.Rejected("retry")
    }
}

/** D-341 3 and 9 checks on the leaf the phone saw on first contact. Pure JVM. */
object LeafBinding {
    private const val DNS_NAME = 2

    /** True when [leaf] carries [host] as a DNS SAN (case-insensitive). */
    fun namesHost(leaf: X509Certificate, host: String): Boolean = try {
        leaf.subjectAlternativeNames.orEmpty().any { it.size >= 2 && it[0] == DNS_NAME && (it[1] as? String).equals(host, ignoreCase = true) }
    } catch (e: CertificateException) {
        false
    }

    /**
     * Null when [leaf] chains to [ca] alone (PKIX, no revocation; the leaf's dates are checked, and the CA's
     * here because PKIX skips the anchor's) and names [tlsHost]; else `leaf_not_signed_by_ca` or `leaf_san`.
     */
    fun reason(leaf: X509Certificate, ca: X509Certificate, tlsHost: String): String? {
        try {
            ca.checkValidity()
            val params = PKIXParameters(setOf(TrustAnchor(ca, null))).apply { isRevocationEnabled = false }
            val path = CertificateFactory.getInstance("X.509").generateCertPath(listOf(leaf))
            CertPathValidator.getInstance("PKIX").validate(path, params)
        } catch (e: CertPathValidatorException) {
            return "leaf_not_signed_by_ca"
        } catch (e: InvalidAlgorithmParameterException) {
            return "leaf_not_signed_by_ca"
        } catch (e: CertificateException) {
            return "leaf_not_signed_by_ca"
        }
        return if (namesHost(leaf, tlsHost)) null else "leaf_san"
    }
}
