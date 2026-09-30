package io.github.livsbittt.rosy.cam.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import io.github.livsbittt.rosy.cam.camera.LensChoice
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map

private val Context.camDataStore: DataStore<Preferences> by preferencesDataStore(name = "cam_settings")

/**
 * Pairing target (host, port, token, source) and the lens setting in app-private DataStore. The address and token
 * never go into the repository (public repo, D-261 6); backups are disabled in the manifest.
 */
class SettingsStore(context: Context) {
    private val store = context.applicationContext.camDataStore

    /** The saved pairing, or null when nothing valid is saved yet. */
    val pairing: Flow<PairingUri?> = store.data
        .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
        .map { prefs ->
            val host = prefs[HOST] ?: return@map null
            val port = prefs[PORT] ?: return@map null
            val token = prefs[TOKEN] ?: return@map null
            val source = prefs[SOURCE] ?: return@map null
            val secure = prefs[SECURE] ?: false
            val pin = prefs[PIN]
            if (PairingUri.validate(host, port, token, source, secure, pin) != null) null
            else PairingUri(host, port, token, source, secure, pin)
        }

    /** Saved lens setting; null until the operator picks one (then [LensChoice.DEFAULT] applies). */
    val lens: Flow<LensChoice?> = store.data
        .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
        .map { prefs -> LensChoice.fromWire(prefs[LENS]) }

    suspend fun saveLens(choice: LensChoice) {
        store.edit { prefs -> prefs[LENS] = choice.wire }
    }

    suspend fun save(pairing: PairingUri) {
        val reason = PairingUri.validate(
            pairing.host, pairing.port, pairing.token, pairing.source, pairing.secure, pairing.pin,
        )
        require(reason == null) { "invalid pairing field: $reason" }
        store.edit { prefs ->
            prefs[HOST] = pairing.host
            prefs[PORT] = pairing.port
            prefs[TOKEN] = pairing.token
            prefs[SOURCE] = pairing.source
            prefs[SECURE] = pairing.secure
            // A new pairing without a pin must not inherit the previous site's pin.
            if (pairing.pin == null) prefs.remove(PIN) else prefs[PIN] = pairing.pin
        }
    }

    private companion object {
        val HOST = stringPreferencesKey("host")
        val PORT = intPreferencesKey("port")
        val TOKEN = stringPreferencesKey("token")
        val SOURCE = stringPreferencesKey("source")
        val SECURE = booleanPreferencesKey("secure")
        val PIN = stringPreferencesKey("pin")
        val LENS = stringPreferencesKey("lens")
    }
}
