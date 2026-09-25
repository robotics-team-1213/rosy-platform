package io.github.livsbittt.rosy.overhead.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map

private val Context.overheadDataStore: DataStore<Preferences> by preferencesDataStore(name = "overhead_settings")

/**
 * Pairing target (host, port, token, source) in app-private DataStore. The address and token
 * never go into the repository (public repo, D-261 6); backups are disabled in the manifest.
 */
class SettingsStore(context: Context) {
    private val store = context.applicationContext.overheadDataStore

    /** The saved pairing, or null when nothing valid is saved yet. */
    val pairing: Flow<PairingUri?> = store.data
        .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
        .map { prefs ->
            val host = prefs[HOST] ?: return@map null
            val port = prefs[PORT] ?: return@map null
            val token = prefs[TOKEN] ?: return@map null
            val source = prefs[SOURCE] ?: return@map null
            if (PairingUri.validate(host, port, token, source) != null) null else PairingUri(host, port, token, source)
        }

    suspend fun save(pairing: PairingUri) {
        val reason = PairingUri.validate(pairing.host, pairing.port, pairing.token, pairing.source)
        require(reason == null) { "invalid pairing field: $reason" }
        store.edit { prefs ->
            prefs[HOST] = pairing.host
            prefs[PORT] = pairing.port
            prefs[TOKEN] = pairing.token
            prefs[SOURCE] = pairing.source
        }
    }

    private companion object {
        val HOST = stringPreferencesKey("host")
        val PORT = intPreferencesKey("port")
        val TOKEN = stringPreferencesKey("token")
        val SOURCE = stringPreferencesKey("source")
    }
}
