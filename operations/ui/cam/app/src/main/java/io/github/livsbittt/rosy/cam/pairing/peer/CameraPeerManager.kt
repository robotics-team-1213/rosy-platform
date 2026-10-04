package io.github.livsbittt.rosy.cam.pairing.peer

import android.content.Context
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** UI and transport share one vault/key owner. Forget and final credential commit are serialized. */
class CameraPeerManager internal constructor(private val settings: SettingsStore,
    val vault: CameraRelationshipVault, val signer: CameraSigner) {
    constructor(context: Context) : this(SettingsStore(context), vault(context), signer(context))
    suspend fun snapshot() = settings.peerSnapshot()
    suspend fun install(result: CameraConnection, expected: SettingsStore.PeerSnapshot, current: () -> Boolean) = writes.withLock {
        settings.installPeer(result, expected) { current() && vault.fence(site(result)) == result.fence }
    }
    suspend fun forget(site: PairableSite) = writes.withLock {
        vault.erase(site)
        settings.forgetPeer(CameraRelationshipVault.origin(site))
    }
    private fun site(result: CameraConnection) = PairableSite(result.link.siteName.orEmpty(), result.link.tlsHost!!, result.link.port)
    companion object {
        /** Intrinsic marked credentials must never fall into legacy bearer reconnect after metadata loss. */
        fun requiredRelationship(link: io.github.livsbittt.rosy.cam.settings.SiteLink?, relationship: String?): String? {
            if (relationship != null) {
                if (link == null || !Regex("[A-Za-z0-9_-]{32}").matches(relationship)) throw io.github.livsbittt.rosy.cam.link.CredentialDenied()
                return relationship
            }
            if (link?.credentialId?.startsWith("cam-peer-") == true) throw io.github.livsbittt.rosy.cam.link.CredentialDenied()
            return null
        }
        private val owners = Any()
        private val writes = Mutex()
        private var storedVault: CameraRelationshipVault? = null
        private var storedSigner: CameraSigner? = null
        private fun vault(context: Context) = synchronized(owners) {
            storedVault ?: CameraRelationshipVault(context.applicationContext).also { storedVault = it }
        }
        private fun signer(context: Context) = synchronized(owners) {
            storedSigner ?: AndroidCameraIdentity(context.applicationContext).also { storedSigner = it }
        }
    }
}
