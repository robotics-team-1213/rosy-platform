package io.github.livsbittt.rosy.cam.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.MutablePreferences
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
 * The site link (D-391 1, [SiteLink]) and the lens setting in app-private DataStore. The token never goes into
 * the repository (public repo, D-261 6); backups are disabled in the manifest.
 *
 * A pairing saved before D-391 (key `host`, and `pin`) is read through [SiteLink.from]: an IP host becomes
 * `manual_host`, a DNS name `tls_host`. The next [save] rewrites it in the new keys.
 */
class SettingsStore(context: Context) {
    private val store = context.applicationContext.camDataStore

    /** The stored record as read: the usable link, plus a salvaged or rejected host for the screen. */
    val stored: Flow<SiteLinkPrefs.Stored> = store.data
        .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
        .map { prefs -> SiteLinkPrefs.read(values(prefs)) }

    /** The saved site link, or null when nothing usable is saved yet. */
    val siteLink: Flow<SiteLink?> = stored.map { it.link }

    /** Saved lens setting; null until the operator picks one (then [LensChoice.DEFAULT] applies). */
    val lens: Flow<LensChoice?> = store.data
        .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
        .map { prefs -> LensChoice.fromWire(prefs[LENS]) }

    suspend fun saveLens(choice: LensChoice) {
        store.edit { prefs -> prefs[LENS] = choice.wire }
    }

    /**
     * Saves [pairing] as the site link. [siteName] is the mDNS service the operator picked, [pairingSubnet] the
     * Wi-Fi subnet at this moment (diagnostic only). Fields the input cannot carry come from the saved link
     * when it is the same site (see [SiteLink.from]).
     */
    suspend fun save(pairing: PairingUri, siteName: String? = null, pairingSubnet: String? = null) {
        store.edit { prefs ->
            val link = SiteLink.from(pairing, siteName, pairingSubnet, previous = decode(prefs))
            val reason = SiteLink.validate(link)
            require(reason == null) { "invalid site link field: $reason" }
            write(prefs, link)
        }
    }

    /**
     * Records the `tls_host` that mDNS showed at this link's `manual_host` (same pinned site CA), so later
     * connects follow the name instead of the address. No-op when the saved link changed meanwhile.
     */
    suspend fun learnTlsHost(expected: SiteLink, tlsHost: String, siteName: String?) {
        store.edit { prefs ->
            val current = decode(prefs) ?: return@edit
            if (current != expected || current.tlsHost != null) return@edit
            val learned = current.copy(tlsHost = SiteLink.normalizeHost(tlsHost), siteName = siteName ?: current.siteName)
            if (SiteLink.validate(learned) == null) write(prefs, learned)
        }
    }

    /** Applies [SiteLinkPrefs.encode]: typed keys for values, removal for nulls (DataStore keys match by name). */
    private fun write(prefs: MutablePreferences, link: SiteLink) {
        SiteLinkPrefs.encode(link).forEach { (name, value) ->
            when (value) {
                null -> prefs.remove(stringPreferencesKey(name))
                is String -> prefs[stringPreferencesKey(name)] = value
                is Int -> prefs[intPreferencesKey(name)] = value
                is Boolean -> prefs[booleanPreferencesKey(name)] = value
                else -> error("unsupported site-link value type for $name")
            }
        }
    }

    private fun values(prefs: Preferences): Map<String, Any?> = prefs.asMap().mapKeys { (key, _) -> key.name }

    private fun decode(prefs: Preferences): SiteLink? = SiteLinkPrefs.decode(values(prefs))

    private companion object {
        val LENS = stringPreferencesKey("lens")
    }
}
