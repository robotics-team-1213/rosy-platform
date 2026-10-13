package io.github.livsbittt.rosy.cam.pairing.peer

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.settings.NsdSiteBrowser
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext

sealed interface CameraPeerState {
    data object Idle : CameraPeerState
    data class Connecting(val site: PairableSite) : CameraPeerState
    data class Pending(val site: PairableSite, val pending: CameraPending) : CameraPeerState
    data class Certificate(val site: PairableSite, val offer: CameraCaOffer) : CameraPeerState
    data class Connected(val site: PairableSite) : CameraPeerState
    data class Failed(val site: PairableSite, val retained: Boolean) : CameraPeerState
    data class Forgetting(val site: PairableSite) : CameraPeerState
}

/** A selected LAN receiver transaction; rotation retains it, explicit cancel/background retires it. */
class CameraPeerViewModel(application: Application) : AndroidViewModel(application) {
    private val manager = CameraPeerManager(application)
    private val mutable = MutableStateFlow<CameraPeerState>(CameraPeerState.Idle)
    val state = mutable.asStateFlow()
    private val saved = MutableStateFlow(emptyList<PairableSite>())
    val remembered = saved.asStateFlow()
    private var worker: Job? = null
    @Volatile private var epoch = 0L
    @Volatile private var client: CameraPeerClient? = null
    private var answer: CompletableDeferred<Boolean>? = null
    private var forgetting = false
    init { refreshRemembered() }
    fun refreshRemembered() { viewModelScope.launch { saved.value = withContext(Dispatchers.IO) { manager.vault.rememberedSites() } } }
    @Synchronized fun confirmCertificate(matches: Boolean) { answer?.complete(matches) }
    @Synchronized fun close() {
        if (forgetting) return
        epoch++; client?.close(); client = null; answer?.complete(false); answer = null
        worker?.cancel(); worker = null; mutable.value = CameraPeerState.Idle
    }
    @Synchronized fun open(site: PairableSite) {
        if (forgetting) return
        close(); val owner = epoch; mutable.value = CameraPeerState.Connecting(site)
        worker = viewModelScope.launch {
            val expected = manager.snapshot()
            var owned: CameraPeerClient? = null
            try {
                val result = withContext(Dispatchers.IO) {
                    val fresh = freshSite(site)
                    check(owner == epoch)
                    CameraPeerClient(fresh, manager.signer, manager.vault, current = { owner == epoch }).also { owned = it; client = it }
                        .connect({ pending -> publish(owner, CameraPeerState.Pending(site, pending)) }, { offer ->
                            val response = CompletableDeferred<Boolean>()
                            val active = synchronized(this@CameraPeerViewModel) {
                                if (owner != epoch) false else { answer = response; mutable.value = CameraPeerState.Certificate(site, offer); true }
                            }
                            if (!active) false else {
                                runBlocking { response.await() }
                            }
                        })
                }
                manager.install(result, expected) { owner == epoch }
                publish(owner, CameraPeerState.Connected(site))
                refreshRemembered()
            } catch (_: Exception) {
                publish(owner, CameraPeerState.Failed(site, runCatching { manager.vault.read(site) != null }.getOrDefault(false)))
            } finally {
                owned?.close()
                synchronized(this@CameraPeerViewModel) { if (owner == epoch) { client = null; answer = null } }
            }
        }
    }
    @Synchronized private fun publish(owner: Long, value: CameraPeerState) { if (epoch == owner) mutable.value = value }
    @Synchronized fun forget(site: PairableSite) {
        if (forgetting) return
        val old = worker; close(); val owner = epoch
        forgetting = true; mutable.value = CameraPeerState.Forgetting(site)
        viewModelScope.launch {
            try {
                old?.cancelAndJoin()
                manager.forget(site)
                refreshRemembered()
                publish(owner, CameraPeerState.Idle)
            } catch (_: Exception) { publish(owner, CameraPeerState.Failed(site, true)) }
            finally { synchronized(this@CameraPeerViewModel) { forgetting = false } }
        }
    }
    private fun freshSite(site: PairableSite): PairableSite {
        val hits = NsdSiteBrowser(getApplication()).browse(5000) { it.tlsHost == site.tlsHost && it.port == site.port }
        require(hits.isNotEmpty()) { "receiver not discovered" }
        val sets = hits.map { it.addresses.mapNotNull { address -> address.hostAddress }.toSet() }
        require(sets.all { it.isNotEmpty() } && sets.all { a -> sets.all { b -> a.intersect(b).isNotEmpty() } }) { "receiver address conflict" }
        return site.copy(address = hits.first().addresses.first().hostAddress)
    }
    override fun onCleared() { close() }
}
