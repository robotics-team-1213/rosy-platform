package io.github.livsbittt.rosy.cam.pairing.peer

import io.github.livsbittt.rosy.cam.link.CredentialDenied
import io.github.livsbittt.rosy.cam.link.CredentialProvider
import io.github.livsbittt.rosy.cam.link.CredentialRenewal
import io.github.livsbittt.rosy.cam.link.CredentialUnavailable
import io.github.livsbittt.rosy.cam.link.SiteMoved
import io.github.livsbittt.rosy.cam.link.SiteResolver
import io.github.livsbittt.rosy.cam.link.SiteRoute
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.time.Instant
import kotlin.coroutines.EmptyCoroutineContext
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext

/** Every frame upgrade proves the remembered receiver/client keys before sending a camera bearer. */
class CameraCredentialProvider(private val manager: CameraPeerManager, private val original: SiteLink,
    private val relationshipId: String, private val resolver: SiteResolver) : CredentialProvider {
    override suspend fun renew(current: () -> Boolean): CredentialRenewal {
        try {
            val expected = manager.snapshot()
            val active = expected.link ?: throw CredentialDenied()
            require(current() && expected.relationshipId == relationshipId && active.tlsHost == original.tlsHost && active.port == original.port &&
                active.source == original.source && active.caPin == original.caPin && active.secure)
            val site = withContext(Dispatchers.IO) {
                resolver.invalidate()
                val route = resolver.resolve()
                if (route is SiteRoute.Discovered) PairableSite(route.sighting.serviceName, original.tlsHost!!, original.port, route.sighting.addresses.first().hostAddress)
                else {
                    // The saved host name is not advertised. The same site may be advertised under a new name.
                    if (route !is SiteRoute.Conflict) followMoved(expected, active, current)
                    throw java.io.IOException("receiver not discovered or conflicted")
                }
            }
            require(current())
            val remembered = manager.vault.read(site) ?: throw CredentialDenied()
            require(remembered.id == relationshipId && remembered.sourceId == original.source)
            val client = CameraPeerClient(site, manager.signer, manager.vault, current)
            val result = client.awaitRemembered()
            require(current() && result.relationship.id == relationshipId && result.link.source == original.source && result.link.caPin == original.caPin)
            manager.install(result, expected, current)
            return CredentialRenewal(result.link.toPairing(), Instant.parse(result.link.expiresAt))
        } catch (failure: PeerRefused) {
            // 409 is the receiver saying the relationship was revoked or replaced: final. Other refusals are no proof that
            // the approval is gone (a restarting site answers 4xx): retry slowly instead of stopping.
            if (failure.status == 409) throw CredentialDenied()
            throw CredentialUnavailable(failure.status)
        } catch (_: IllegalArgumentException) { throw CredentialDenied() }
        catch (_: PeerKeyChanged) { throw CredentialDenied() }
        catch (_: PeerApprovalExpired) { throw CredentialDenied() }
    }
    /**
     * Tries each other advertised host name with the remembered approval moved onto it. Only a full proof (pinned CA,
     * leaf bound to the name, same receiver id and key, signed challenge) saves the new name; any failure just skips
     * that advert, so a different site or a spoofed advert changes nothing. Throws [SiteMoved] after saving.
     */
    private suspend fun followMoved(expected: SettingsStore.PeerSnapshot, active: SiteLink, current: () -> Boolean) {
        val old = PairableSite(active.siteName.orEmpty(), original.tlsHost!!, original.port)
        for (sighting in resolver.otherHosts()) {
            val candidate = PairableSite(sighting.serviceName, SiteLink.normalizeHost(sighting.tlsHost), sighting.port, sighting.addresses.first().hostAddress)
            val result = try {
                suspendCancellableCoroutine<CameraConnection> { continuation ->
                    val client = CameraPeerClient(candidate, manager.signer, manager.vault, current, moveFrom = old)
                    continuation.invokeOnCancellation { client.close() }
                    Dispatchers.IO.dispatch(EmptyCoroutineContext, Runnable {
                        try {
                            val connection = client.connect({ throw CredentialDenied() }, { false })
                            if (continuation.isActive) continuation.resume(connection)
                        } catch (failure: Exception) { if (continuation.isActive) continuation.resumeWithException(failure) }
                        finally { client.close() }
                    })
                }
            } catch (cancelled: kotlinx.coroutines.CancellationException) { throw cancelled } catch (_: Exception) { continue }
            if (result.relationship.id != relationshipId || result.link.source != original.source || result.link.caPin != original.caPin) continue
            manager.install(result, expected, current)
            manager.vault.erase(old)
            throw SiteMoved()
        }
    }
    private suspend fun CameraPeerClient.awaitRemembered(): CameraConnection = suspendCancellableCoroutine { continuation ->
        continuation.invokeOnCancellation { close() }
        Dispatchers.IO.dispatch(EmptyCoroutineContext, Runnable {
            try {
                val result = connect({ throw CredentialDenied() }, { false })
                if (continuation.isActive) continuation.resume(result)
            } catch (failure: Exception) { if (continuation.isActive) continuation.resumeWithException(failure) }
            finally { close() }
        })
    }
}
