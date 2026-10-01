package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.settings.SettingsStore
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.io.IOException
import kotlin.coroutines.CoroutineContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Drives a [PairingClient] for the screen: one step at a time on [io], polls no faster than every
 * [POLL_INTERVAL_MS] (S2 `POLL_TOO_FAST`) and never before a 429's Retry-After. A poll that fails on the network
 * is retried at the same pace until the request's own deadline; a changed site certificate ends the attempt.
 */
class PairingSession(
    private val client: PairingClient,
    private val scope: CoroutineScope,
    private val io: CoroutineContext = Dispatchers.IO,
    private val sleep: suspend (Long) -> Unit = { delay(it) },
) {
    private val mutableState = MutableStateFlow<PairingState>(PairingState.Discover)
    val state: StateFlow<PairingState> = mutableState.asStateFlow()

    /** True while a network step runs (the screen shows "요청하는 중…" and disables buttons). */
    private val mutableBusy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = mutableBusy.asStateFlow()

    private val steps = Mutex()
    private var job: Job? = null

    /** True from the tap on "같습니다/다릅니다" until the answer step ends; nothing may cancel or repeat it. */
    @Volatile
    private var answering = false

    /** Starts (or restarts after a final state) an attempt. Ignored while one is starting or an answer runs. */
    fun start(site: PairableSite) {
        if (answering || (mutableBusy.value && job?.isActive == true)) return
        mutableBusy.value = true // before launch: a second tap in the same frame sees it
        job?.cancel()
        job = scope.launch {
            step(failure = { PairingState.Rejected(it) }) { client.start(site) }
            while (client.state.isWaiting()) {
                sleep(nextPollDelayMs(client.retryAfterS))
                step(failure = { reason ->
                    // Another certificate mid-pairing is not a network blip: drop the attempt (D-341 8).
                    if (reason == LEAF_CHANGED) PairingState.Rejected(reason).also { client.cancel() } else null
                }) { client.poll() }
            }
        }
    }

    /** The installer's answer on the fingerprint step. A double tap or a later cancel cannot interrupt it. */
    fun answer(matches: Boolean) {
        if (answering || client.state !is PairingState.ConfirmFingerprint) return
        answering = true
        mutableBusy.value = true
        // On an I/O failure the client has already discarded the link and ended as `confirm_unanswered`.
        job = scope.launch {
            try {
                step(failure = { null }) { client.answerFingerprint(matches) }
            } finally {
                answering = false
            }
        }
    }

    /** Drops the attempt; ignored while an answer (save + confirm) runs, which ends on its own. */
    fun cancel() {
        if (answering) return
        job?.cancel()
        job = scope.launch {
            steps.withLock { client.cancel() }
            mutableBusy.value = false
            mutableState.value = PairingState.Discover
        }
    }

    /** Waits for the running work; for tests. */
    suspend fun join() {
        job?.join()
    }

    /**
     * Runs one client step off the main thread. An I/O failure maps through [failure] to a final state, or
     * (null) leaves the attempt where it is so the poll loop tries again. Any other exception ends the attempt as
     * `internal` (keeping a credential id the client recorded) so nothing escapes [scope].
     */
    private suspend fun step(failure: (String) -> PairingState?, call: () -> PairingState) {
        mutableBusy.value = true
        val next = try {
            steps.withLock {
                withContext(io) {
                    try {
                        call()
                    } catch (e: IOException) {
                        failure(networkReason(e)) ?: client.state
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: RuntimeException) {
                        val credential = (client.state as? PairingState.Rejected)?.credentialId
                        if (client.state.isWaiting() || client.state is PairingState.ConfirmFingerprint) client.cancel()
                        PairingState.Rejected("internal", credential)
                    }
                }
            }
        } finally {
            mutableBusy.value = false
        }
        mutableState.value = next
    }

    private fun PairingState.isWaiting(): Boolean =
        this is PairingState.Requested || this is PairingState.AwaitingApproval

    companion object {
        const val POLL_INTERVAL_MS = 2_000L
        const val LEAF_CHANGED = "leaf_changed"

        /** A site's Retry-After is honoured up to this; a larger value cannot park the screen. */
        const val MAX_RETRY_AFTER_MS = 30_000L

        /** max(2 s, min(Retry-After, 30 s)). */
        fun nextPollDelayMs(retryAfterS: Long?): Long =
            maxOf(POLL_INTERVAL_MS, (retryAfterS ?: 0L).coerceIn(0L, MAX_RETRY_AFTER_MS / 1_000L) * 1_000L)

        /** `leaf_changed` when the session's pinned first-contact leaf was replaced, else `unreachable`. */
        fun networkReason(e: Throwable): String =
            if (generateSequence(e) { it.cause }.any { it.message?.contains(FirstContactTrust.LEAF_CHANGED) == true }) {
                LEAF_CHANGED
            } else {
                "unreachable"
            }
    }
}

/**
 * [PairingLinkStore] on the app's DataStore. The client calls it from the IO dispatcher, so the blocking bridge
 * never runs on the main thread. [discard] puts back the link that [save] replaced.
 */
class SettingsPairingStore(private val settings: SettingsStore) : PairingLinkStore {
    private var previous: SiteLink? = null

    override fun save(link: SiteLink) {
        previous = runBlocking { settings.replace(link) }
    }

    override fun discard(link: SiteLink) {
        runBlocking { settings.restore(previous, link) }
        previous = null
    }
}
