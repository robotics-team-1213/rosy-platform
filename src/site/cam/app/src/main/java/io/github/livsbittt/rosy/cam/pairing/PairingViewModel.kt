package io.github.livsbittt.rosy.cam.pairing

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** The pairing attempt on screen and the session that drives it. */
data class PairingAttempt(val site: PairableSite, val session: PairingSession)

/**
 * Holds the pairing attempt across configuration changes (rotation), so the code on screen, the poll loop and an
 * answer in flight survive the Activity being recreated. The attempt lives until [close] or until the app's task
 * goes away; the server expires an abandoned request by itself (300 s pending, 120 s to confirm).
 */
class PairingViewModel(application: Application) : AndroidViewModel(application) {
    private val settings = SettingsStore(application)
    private val mutableAttempt = MutableStateFlow<PairingAttempt?>(null)
    val attempt: StateFlow<PairingAttempt?> = mutableAttempt.asStateFlow()

    /** Opens a new attempt for [site] and starts it; the same site already open is kept as is. */
    fun open(site: PairableSite, deviceLabel: String, appVersion: String) {
        if (mutableAttempt.value?.site == site) return
        mutableAttempt.value?.session?.cancel()
        val client = PairingClient(HttpPairingTransport(site), deviceLabel, appVersion, SettingsPairingStore(settings))
        val session = PairingSession(client, viewModelScope)
        mutableAttempt.value = PairingAttempt(site, session)
        session.start(site)
    }

    /** Leaves the pairing screen. An answer that is running finishes on its own ([PairingSession.cancel]). */
    fun close() {
        mutableAttempt.value?.session?.cancel()
        mutableAttempt.value = null
    }
}
