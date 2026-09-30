package io.github.livsbittt.rosy.cam.link

import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Base64
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager
import okhttp3.OkHttpClient

/** `sha256/` + base64url without padding of SHA-256(certificate DER); same as Python `protocol.cert_pin`. */
fun certPin(der: ByteArray): String =
    PIN_PREFIX + Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(der))

private const val PIN_PREFIX = "sha256/"

/** The served chain has no certificate with the paired pin. Marker text survives TLS stacks that drop the cause. */
class PinMismatchException(detail: String) : CertificateException("$MARKER: $detail") {
    companion object {
        const val MARKER = "rosy-pin-mismatch"
    }
}

/**
 * Trusts one site certificate, chosen by [pin] from the pairing link (D-341 9). No system or
 * user CA is consulted, and nothing outside this link's OkHttp client changes.
 *
 * - The pinned certificate must appear in the chain the server sends. A CA pin therefore needs
 *   the server to send leaf + CA; a leaf pin works with a leaf-only server.
 * - When the pin is a CA (index > 0), the leaf must chain to it: the platform PKIX validator runs
 *   with that one certificate as its only trust anchor (signatures, validity, CA constraints).
 * - When the pin is the leaf, only its validity period is checked; the pin already names it. The site
 *   side (`rosy-vision pair-link`) issues CA pins only (D-341 9); leaf pins are still accepted so links
 *   printed before that rule keep working.
 * - The pinned certificate's own validity period is always checked (PKIX skips the anchor's dates).
 * - Hostname verification is not done here; OkHttp's verifier still checks the SAN (DNS or IP).
 */
class PinnedTrustManager(private val pin: String) : X509TrustManager {
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        if (chain.isNullOrEmpty()) throw CertificateException("empty server certificate chain")
        val index = chain.indexOfFirst { certPin(it.encoded) == pin }
        if (index < 0) throw PinMismatchException("no certificate in the ${chain.size}-certificate chain matches the paired pin")
        // PKIX never checks the trust anchor's own dates, so the pinned certificate is checked here (review n2).
        chain[index].checkValidity()
        if (index == 0) return
        // A pin above the leaf must be a CA; a pinned leaf sent after someone else's leaf is not one (review m3).
        if (chain[index].basicConstraints < 0) {
            throw CertificateException("pinned certificate at chain position $index is not a CA")
        }
        val anchors = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null)
            setCertificateEntry("site", chain[index])
        }
        val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(anchors) }
        val delegate = factory.trustManagers.filterIsInstance<X509TrustManager>().first()
        delegate.checkServerTrusted(chain.copyOfRange(0, index + 1), authType)
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        throw CertificateException("client certificates are not accepted")
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

/** Adds the pinned trust to [builder] when [pin] is set; otherwise leaves the system trust store in place. */
fun OkHttpClient.Builder.pinnedTo(pin: String?): OkHttpClient.Builder {
    if (pin == null) return this
    val trust = PinnedTrustManager(pin)
    val context = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
    return sslSocketFactory(context.socketFactory, trust)
}
