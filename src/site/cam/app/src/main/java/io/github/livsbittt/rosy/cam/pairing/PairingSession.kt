package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.settings.SettingsStore
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.io.IOException
import kotlin.coroutines.CoroutineContext
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

    fun start(site: PairableSite) {
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

    /** The installer's answer on the fingerprint step. */
    fun answer(matches: Boolean) {
        if (client.state !is PairingState.ConfirmFingerprint) return
        job?.cancel()
        // On an I/O failure the client has already discarded the link and ended as `confirm_failed`.
        job = scope.launch { step(failure = { null }) { client.answerFingerprint(matches) } }
    }

    fun cancel() {
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
     * (null) leaves the attempt where it is so the poll loop tries again.
     */
    private suspend fun step(failure: (String) -> PairingState?, call: () -> PairingState) {
        mutableBusy.value = true
        val next = steps.withLock {
            withContext(io) {
                try {
                    call()
                } catch (e: IOException) {
                    failure(networkReason(e)) ?: client.state
                }
            }
        }
        mutableBusy.value = false
        mutableState.value = next
    }

    private fun PairingState.isWaiting(): Boolean =
        this is PairingState.Requested || this is PairingState.AwaitingApproval

    companion object {
        const val POLL_INTERVAL_MS = 2_000L
        const val LEAF_CHANGED = "leaf_changed"

        fun nextPollDelayMs(retryAfterS: Long?): Long = maxOf(POLL_INTERVAL_MS, (retryAfterS ?: 0L) * 1_000L)

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
