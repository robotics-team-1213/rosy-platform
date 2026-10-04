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
import java.time.Instant
import org.json.JSONObject
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.first
import java.util.UUID
import io.github.livsbittt.rosy.cam.pairing.peer.CameraConnection

private val Context.camDataStore: DataStore<Preferences> by preferencesDataStore(name = "cam_settings")

/**
 * The site link (D-391 1, [SiteLink]) and the lens setting in app-private DataStore. The token never goes into
 * the repository (public repo, D-261 6); backups are disabled in the manifest.
 *
 * A pairing saved before D-391 (key `host`, and `pin`) is read through [SiteLink.from]: an IP host becomes
 * `manual_host`, a DNS name `tls_host`. The next [save] rewrites it in the new keys.
 */
class SettingsStore internal constructor(private val store: DataStore<Preferences>) {
    constructor(context: Context) : this(context.applicationContext.camDataStore)
    private data class Rollback(val previous: SiteLink?, val replaced: SiteLink, val revision: String, val relationship: String?)
    private var rollback: Rollback? = null

    data class PeerSnapshot(val link: SiteLink?, val revision: String, val relationshipId: String?)
    suspend fun peerSnapshot(): PeerSnapshot = store.data.first().let {
        PeerSnapshot(decode(it), it[LINK_REVISION] ?: "0", it[PEER_RELATIONSHIP])
    }
    /** The DataStore transaction fences newer manual links, receiver choices and local forgetting. */
    suspend fun installPeer(connection: CameraConnection, expected: PeerSnapshot, valid: () -> Boolean) {
        store.edit { prefs ->
            require(prefs[DEVELOPMENT_POLICY] == null && (prefs[LINK_REVISION] ?: "0") == expected.revision && decode(prefs) == expected.link)
            check(valid()) { "camera connection superseded" }
            require(SiteLink.validate(connection.link) == null)
            write(prefs, connection.link)
            prefs[PEER_RELATIONSHIP] = connection.relationship.id
        }
    }
    suspend fun forgetPeer(origin: String) {
        store.edit { prefs ->
            val current = decode(prefs)
            if (current?.tlsHost != null && "https://${current.tlsHost}:${current.port}" == origin && prefs[PEER_RELATIONSHIP] != null) {
                SiteLinkPrefs.encode(current).keys.forEach { prefs.remove(stringPreferencesKey(it)) }
                prefs.remove(PEER_RELATIONSHIP); prefs[LINK_REVISION] = UUID.randomUUID().toString()
            }
        }
    }

    /** The stored record as read: the usable link, plus a salvaged or rejected host for the screen. */
    val stored: Flow<SiteLinkPrefs.Stored> = store.data
        .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
        .map { prefs ->
            val saved = SiteLinkPrefs.read(values(prefs))
            val usable = prefs[DEVELOPMENT_POLICY] == null ||
                (developmentPolicy(prefs) != null && saved.link?.expiresAt?.let { runCatching { Instant.parse(it) > Instant.now() }.getOrDefault(false) } == true)
            if (usable) saved else SiteLinkPrefs.Stored(null)
        }

    // Keep the expired scope visible so the operator can revoke it; it is never returned by siteLink.
    val development: Flow<LinkPolicy?> = store.data.map { prefs ->
        prefs[DEVELOPMENT_POLICY]?.let { runCatching { LinkPolicy.parse(JSONObject(it), now = Instant.EPOCH) }.getOrNull() }
    }

    suspend fun importDevelopment(bootstrap: DevelopmentBootstrap) {
        store.edit { prefs ->
            // Validate again inside the write: an import preview may have outlived its deadline.
            LinkPolicy.parse(JSONObject(bootstrap.policyJson))
            require(Instant.parse(bootstrap.link.expiresAt) > Instant.now()) { "credential expired" }
            write(prefs, bootstrap.link)
            prefs[DEVELOPMENT_POLICY] = bootstrap.policyJson
        }
    }

    suspend fun revokeDevelopment() {
        store.edit { prefs ->
            if (prefs[DEVELOPMENT_POLICY] == null) return@edit
            decode(prefs)?.let { link -> SiteLinkPrefs.encode(link).keys.forEach { prefs.remove(stringPreferencesKey(it)) } }
            prefs.remove(DEVELOPMENT_POLICY)
        }
    }

    private fun developmentPolicy(prefs: Preferences): LinkPolicy? = prefs[DEVELOPMENT_POLICY]?.let {
        runCatching { LinkPolicy.parse(JSONObject(it)) }.getOrNull()
    }

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
            require(prefs[DEVELOPMENT_POLICY] == null) { "revoke development link before editing" }
            val link = SiteLink.from(pairing, siteName, pairingSubnet, previous = decode(prefs))
            val reason = SiteLink.validate(link)
            require(reason == null) { "invalid site link field: $reason" }
            write(prefs, link)
            prefs.remove(DEVELOPMENT_POLICY)
        }
    }

    /**
     * Saves a ready [link] (a `rosy-pair/1` result) as is and returns what it replaced, so a failed confirm can
     * put that back with [restore].
     */
    suspend fun replace(link: SiteLink): SiteLink? {
        require(SiteLink.validate(link) == null) { "invalid site link" }
        var previous: SiteLink? = null
        store.edit { prefs ->
            require(prefs[DEVELOPMENT_POLICY] == null) { "revoke development link before pairing" }
            previous = decode(prefs)
            val priorPeer = prefs[PEER_RELATIONSHIP]
            write(prefs, link)
            rollback = Rollback(previous, link, prefs[LINK_REVISION]!!, priorPeer)
            prefs.remove(DEVELOPMENT_POLICY)
        }
        return previous
    }

    /** Undoes [replace]: writes [previous] back, or removes every site-link key when there was none. */
    suspend fun restore(previous: SiteLink?, replaced: SiteLink) {
        store.edit { prefs ->
            val owned = rollback ?: return@edit
            if (owned.replaced !== replaced || owned.previous != previous || owned.revision != prefs[LINK_REVISION] || decode(prefs) != replaced) return@edit
            if (previous != null) {
                write(prefs, previous)
                if (owned.relationship != null) prefs[PEER_RELATIONSHIP] = owned.relationship
            } else {
                SiteLinkPrefs.encode(replaced).keys.forEach { prefs.remove(stringPreferencesKey(it)) }
            }
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
        prefs[LINK_REVISION] = UUID.randomUUID().toString()
        prefs.remove(PEER_RELATIONSHIP)
        rollback = null
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
        val DEVELOPMENT_POLICY = stringPreferencesKey("development_link_policy")
        val LINK_REVISION = stringPreferencesKey("site_link_revision")
        val PEER_RELATIONSHIP = stringPreferencesKey("camera_peer_relationship")
    }
}
