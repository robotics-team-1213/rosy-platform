package io.github.livsbittt.rosy.cam.pairing

import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.io.IOException
import java.net.InetAddress
import java.net.UnknownHostException
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLPeerUnverifiedException
import javax.net.ssl.X509TrustManager
import okhttp3.Dns
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/**
 * TLS trust for one pairing session, exactly D-341 3 and 8. Before pairing the phone has no site CA, so the
 * first handshake **records the leaf without validating it**; every later handshake of the same session is
 * accepted only when it presents that same leaf (DER-equal). Trust in the site comes from the operator typing
 * the code bound to this leaf (D-341 3) and the installer matching the CA fingerprint (D-341 4), and the
 * delivered CA must then sign this leaf (D-341 9, [LeafBinding]). Never used for the frame link.
 */
class FirstContactTrust : X509TrustManager {
    @Volatile
    var leaf: X509Certificate? = null
        private set

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        if (chain.isNullOrEmpty()) throw CertificateException("empty server certificate chain")
        val seen = chain[0]
        synchronized(this) {
            val recorded = leaf
            if (recorded == null) {
                leaf = seen
            } else if (!recorded.encoded.contentEquals(seen.encoded)) {
                throw CertificateException("$LEAF_CHANGED: the site served another certificate during pairing")
            }
        }
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        throw CertificateException("client certificates are not accepted")
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

    companion object {
        const val LEAF_CHANGED = "rosy-pair-leaf-changed"
    }
}

/**
 * [PairingTransport] over the S2 routes `/api/fleet/pairing/v1/...` (rosy-00 a83653e3, reviewed 920bef4d).
 * One instance per pairing attempt: it owns the [FirstContactTrust] of that attempt.
 *
 * TCP goes to the address mDNS resolved ([PairableSite.address]); the URL, SNI and the SAN check use
 * `tls_host`, as on the frame link (D-391 1). Hostname verification is the SAN check in [PairingClient.start]
 * on the recorded leaf (`leaf_san`); later handshakes can only present that same leaf.
 */
class HttpPairingTransport(
    private val site: PairableSite,
    builder: OkHttpClient.Builder = OkHttpClient.Builder(),
) : PairingTransport {
    val trust = FirstContactTrust()

    private val client: OkHttpClient = builder
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .callTimeout(15, TimeUnit.SECONDS)
        .sslSocketFactory(SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }.socketFactory, trust)
        .hostnameVerifier { _, _ -> true }
        .dns(SiteAddressDns(site))
        // No silent replay: a lost confirm reply must surface as confirm_unanswered, not be resent behind our back.
        .retryOnConnectionFailure(false)
        .followRedirects(false)
        .followSslRedirects(false)
        .cache(null)
        .build()

    override fun firstContactLeaf(site: PairableSite): X509Certificate {
        // Any route completes the handshake; the reply is ignored. A non-TLS listener fails here.
        try {
            client.newCall(Request.Builder().url(url("requests", "-")).get().build()).execute().close()
        } catch (e: SSLPeerUnverifiedException) {
            // Not expected (the verifier accepts); the recorded leaf, if any, still decides below.
        }
        return trust.leaf ?: throw IOException("no certificate recorded from ${site.tlsHost}")
    }

    override fun request(site: PairableSite, body: ByteArray): ByteArray =
        call(Request.Builder().url(url("requests")).post(body.toRequestBody(JSON)).build())

    override fun reveal(site: PairableSite, requestId: String, pollKey: String, body: ByteArray): ByteArray =
        call(authorized(url("requests", requestId, "reveal"), pollKey).post(body.toRequestBody(JSON)).build())

    override fun poll(site: PairableSite, requestId: String, pollKey: String): ByteArray =
        call(authorized(url("requests", requestId), pollKey).get().build())

    override fun confirm(site: PairableSite, requestId: String, pollKey: String, body: ByteArray): ByteArray =
        call(authorized(url("requests", requestId, "confirm"), pollKey).post(body.toRequestBody(JSON)).build())

    private fun url(vararg segments: String): HttpUrl = HttpUrl.Builder()
        .scheme("https")
        .host(site.tlsHost)
        .port(site.port)
        .apply {
            BASE_SEGMENTS.forEach { addPathSegment(it) }
            segments.forEach { addPathSegment(it) }
        }
        .build()

    private fun authorized(url: HttpUrl, pollKey: String): Request.Builder =
        Request.Builder().url(url).header("Authorization", "Bearer $pollKey").header("Cache-Control", "no-store")

    /** The reply body of a 2xx; anything else becomes [PairingRefused] with the S2 code and Retry-After. */
    private fun call(request: Request): ByteArray = client.newCall(request).execute().use { response ->
        val body = response.peekBody(MAX_REPLY_BYTES).bytes()
        if (response.isSuccessful) return body
        throw PairingRefused(response.code, errorCode(body), response.header("Retry-After")?.trim()?.toLongOrNull())
    }

    companion object {
        const val BASE = "/api/fleet/pairing/v1"
        private val BASE_SEGMENTS = BASE.trim('/').split('/')
        private val JSON = "application/json".toMediaType()

        /**
         * A pairing reply is a few KiB (the result carries one CA PEM). `peekBody` silently truncates a longer body
         * at this size; the cut JSON then fails to parse and ends the attempt as an invalid reply.
         */
        private const val MAX_REPLY_BYTES = 64L * 1024

        /** S2 refusals are FastAPI `{"detail": {"code": …}}`; a bare `{"code": …}` is read too. */
        fun errorCode(body: ByteArray): String? {
            val json = PairingJson.readObject(body) ?: return null
            val detail = json.opt("detail") as? JSONObject
            return (detail?.opt("code") ?: json.opt("code")) as? String
        }
    }
}

/** `tls_host` resolves to the mDNS address only (never system DNS, which cannot resolve `.local` on Android). */
private class SiteAddressDns(private val site: PairableSite) : Dns {
    override fun lookup(hostname: String): List<InetAddress> {
        val address = site.address
        if (!hostname.equals(site.tlsHost, ignoreCase = true) || address == null || !SiteLink.isIpLiteral(address)) {
            throw UnknownHostException("pairing dials only the discovered address of ${site.tlsHost}")
        }
        // An IP literal (checked above): InetAddress parses it without any lookup.
        return listOf(InetAddress.getByName(address))
    }
}
