package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.settings.PairingUri
import java.time.Instant
import java.io.IOException

data class CredentialRenewal(val pairing: PairingUri, val expiresAt: Instant)
fun interface CredentialProvider { suspend fun renew(current: () -> Boolean): CredentialRenewal }
class CredentialDenied : IOException("remembered camera authorization unavailable")
