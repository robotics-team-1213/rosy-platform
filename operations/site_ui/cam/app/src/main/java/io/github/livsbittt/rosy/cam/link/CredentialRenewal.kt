package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.settings.PairingUri
import java.time.Instant
import java.io.IOException

data class CredentialRenewal(val pairing: PairingUri, val expiresAt: Instant)
fun interface CredentialProvider { suspend fun renew(current: () -> Boolean): CredentialRenewal }
class CredentialDenied : IOException("remembered camera authorization unavailable")

/** The site answered the renewal with a refusal (HTTP 4xx). It may be restarting; retry slowly, never stop the link. */
class CredentialUnavailable(val status: Int) : IOException("site refused camera authorization: HTTP $status")

/** The site is advertised under another host name and the saved link now follows it; restart the session. */
class SiteMoved : IOException("site moved to another host name")
