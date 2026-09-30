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

    /** The saved site link, or null when nothing valid is saved yet. */
    val siteLink: Flow<SiteLink?> = store.data
        .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
        .map(::decode)

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
            val learned = current.copy(tlsHost = tlsHost, siteName = siteName ?: current.siteName)
            if (SiteLink.validate(learned) == null) write(prefs, learned)
        }
    }

    private fun write(prefs: MutablePreferences, link: SiteLink) {
        prefs.remove(LEGACY_HOST)
        prefs.remove(LEGACY_PIN)
        prefs.putOrRemove(TLS_HOST, link.tlsHost)
        prefs.putOrRemove(MANUAL_HOST, link.manualHost)
        prefs.putOrRemove(SITE_NAME, link.siteName)
        // A new pairing without a pin must not inherit the previous site's pin.
        prefs.putOrRemove(CA_PIN, link.caPin)
        prefs.putOrRemove(EXPIRES_AT, link.expiresAt)
        prefs.putOrRemove(PAIRING_SUBNET, link.pairingSubnet)
        prefs[ROLE] = link.role
        prefs[PORT] = link.port
        prefs[TOKEN] = link.token
        prefs[SOURCE] = link.source
        prefs[SECURE] = link.secure
    }

    private fun MutablePreferences.putOrRemove(key: Preferences.Key<String>, value: String?) {
        if (value == null) remove(key) else this[key] = value
    }

    private fun decode(prefs: Preferences): SiteLink? {
        val port = prefs[PORT] ?: return null
        val token = prefs[TOKEN] ?: return null
        val source = prefs[SOURCE] ?: return null
        val secure = prefs[SECURE] ?: false
        val legacyHost = prefs[LEGACY_HOST]
        val link = if (legacyHost != null) {
            SiteLink.from(PairingUri(legacyHost, port, token, source, secure, prefs[LEGACY_PIN]))
        } else {
            SiteLink(
                siteName = prefs[SITE_NAME],
                tlsHost = prefs[TLS_HOST],
                port = port,
                caPin = prefs[CA_PIN],
                token = token,
                source = source,
                secure = secure,
                manualHost = prefs[MANUAL_HOST],
                role = prefs[ROLE] ?: SiteLink.ROLE,
                expiresAt = prefs[EXPIRES_AT],
                pairingSubnet = prefs[PAIRING_SUBNET],
            )
        }
        return link.takeIf { SiteLink.validate(it) == null }
    }

    private companion object {
        // Before D-391: one dialled host (IP or name) and the pin.
        val LEGACY_HOST = stringPreferencesKey("host")
        val LEGACY_PIN = stringPreferencesKey("pin")

        // D-391 1 site-link fields.
        val SITE_NAME = stringPreferencesKey("site_name")
        val TLS_HOST = stringPreferencesKey("tls_host")
        val MANUAL_HOST = stringPreferencesKey("manual_host")
        val CA_PIN = stringPreferencesKey("ca_pin")
        val ROLE = stringPreferencesKey("role")
        val EXPIRES_AT = stringPreferencesKey("expires_at")
        val PAIRING_SUBNET = stringPreferencesKey("pairing_subnet")
        val PORT = intPreferencesKey("port")
        val TOKEN = stringPreferencesKey("token")
        val SOURCE = stringPreferencesKey("source")
        val SECURE = booleanPreferencesKey("secure")
        val LENS = stringPreferencesKey("lens")
    }
}
