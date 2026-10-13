package io.github.livsbittt.rosy.cam.pairing.peer

import io.github.livsbittt.rosy.cam.link.CredentialDenied
import io.github.livsbittt.rosy.cam.link.CredentialProvider
import io.github.livsbittt.rosy.cam.link.CredentialRenewal
import io.github.livsbittt.rosy.cam.link.SiteResolver
import io.github.livsbittt.rosy.cam.link.SiteRoute
import io.github.livsbittt.rosy.cam.pairing.PairableSite
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
                val route = resolver.resolve() as? SiteRoute.Discovered ?: throw java.io.IOException("receiver not discovered or conflicted")
                PairableSite(route.sighting.serviceName, original.tlsHost!!, original.port, route.sighting.addresses.first().hostAddress)
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
            if (failure.status in setOf(400, 401, 403, 404, 409)) throw CredentialDenied()
            throw failure
        } catch (_: IllegalArgumentException) { throw CredentialDenied() }
        catch (_: PeerKeyChanged) { throw CredentialDenied() }
        catch (_: PeerApprovalExpired) { throw CredentialDenied() }
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
