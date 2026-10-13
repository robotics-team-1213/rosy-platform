package io.github.livsbittt.rosy.pilot

import okhttp3.OkHttpClient
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.CertPathValidator
import java.security.cert.PKIXParameters
import java.security.cert.TrustAnchor
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

data class PeerCaOffer(val pem: String, val sha256: String, val hostname: String)

/** D341 limited first-contact capture. Only anonymous pairing routes may use this client. */
internal class PeerFirstContact : X509TrustManager {
    @Volatile var leaf: X509Certificate? = null
        private set
    @Synchronized override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        require(!chain.isNullOrEmpty())
        val seen = chain!![0]
        leaf?.let { require(it.encoded.contentEquals(seen.encoded)) { "first-contact leaf changed" } }
        leaf = seen
    }
    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = throw java.security.cert.CertificateException("client certificates unavailable")
    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

internal object PeerTls {
    fun ca(pem: String): X509Certificate {
        require(pem.toByteArray(Charsets.UTF_8).size <= 8192)
        val certificates = CertificateFactory.getInstance("X.509").generateCertificates(pem.byteInputStream())
        require(certificates.size == 1)
        return (certificates.single() as X509Certificate).also { require(it.basicConstraints >= 0); it.checkValidity() }
    }
    /** The physically compared CA must sign the exact first-contact leaf and name the selected hostname. */
    fun bind(offer: PeerCaOffer, leaf: X509Certificate, hostname: String) {
        require(offer.hostname == hostname)
        val ca = ca(offer.pem); require(PeerProof.hash(ca.encoded) == offer.sha256)
        require(leaf.subjectAlternativeNames.orEmpty().any { it.size >= 2 && it[0] == 2 && (it[1] as? String).equals(hostname, true) })
        ca.checkValidity(); leaf.checkValidity()
        val params = PKIXParameters(setOf(TrustAnchor(ca, null))).apply { isRevocationEnabled = false }
        val path = CertificateFactory.getInstance("X.509").generateCertPath(listOf(leaf))
        CertPathValidator.getInstance("PKIX").validate(path, params)
    }
    fun firstContact(client: OkHttpClient, trust: PeerFirstContact): OkHttpClient = client.newBuilder()
        .sslSocketFactory(SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }.socketFactory, trust).build()
    fun pinned(client: OkHttpClient, pem: String?): OkHttpClient {
        if (pem == null) return client
        val certificate = ca(pem)
        val anchors = KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null, null); setCertificateEntry("receiver", certificate) }
        val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(anchors) }
        val trust = factory.trustManagers.filterIsInstance<X509TrustManager>().single()
        return client.newBuilder().sslSocketFactory(SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }.socketFactory, trust).build()
    }
}
