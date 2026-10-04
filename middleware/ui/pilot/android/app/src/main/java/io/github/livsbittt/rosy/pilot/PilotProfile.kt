package io.github.livsbittt.rosy.pilot

import io.github.livsbittt.rosy.cam.settings.LinkPolicy
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager
import okhttp3.OkHttpClient
import org.json.JSONObject

class RobotTarget(val id: String, val host: String, val port: Int, val credential: String) {
    override fun toString() = "RobotTarget(id=$id, host=$host, port=$port, credential=<redacted>)"
}

class PilotProfile(val policy: LinkPolicy, val ca: X509Certificate, val robots: List<RobotTarget>) {
    override fun toString() = "PilotProfile(site=${policy.siteName}, robots=${robots.size}, expires=${policy.expiresAt})"
    fun authorized(target: RobotTarget) = policy.permits(target.id, "_rosy._tcp", target.host, true)
    fun client(target: RobotTarget, candidates: CandidateStore): OkHttpClient {
        val anchors = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null); setCertificateEntry("site", ca)
        }
        val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(anchors) }
        val trust = factory.trustManagers.filterIsInstance<X509TrustManager>().single()
        val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
        return OkHttpClient.Builder().sslSocketFactory(tls.socketFactory, trust)
            .dns(object : okhttp3.Dns { override fun lookup(name: String): List<java.net.InetAddress> {
                check(authorized(target) && name == target.host) { "development scope expired" }
                ca.checkValidity()
                val addresses = candidates.addresses(name, target.port) ?: throw java.net.UnknownHostException("not discovered")
                return addresses.map { java.net.InetAddress.getByName(it) }
            } })
            .followRedirects(false).followSslRedirects(false)
            .protocols(listOf(okhttp3.Protocol.HTTP_1_1))
            .connectTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
            .build()
    }
    companion object {
        fun parse(text: String): PilotProfile {
            require(text.toByteArray().size <= 131072) { "profile too large" }
            val envelope = JSONObject(text)
            require(envelope.keys().asSequence().toSet() == setOf("policy", "ca_pem", "robots")) { "invalid profile" }
            val policy = LinkPolicy.parse(envelope.getJSONObject("policy"))
            require(policy.mode == "development") { "development profile required" }
            val certificates = CertificateFactory.getInstance("X.509").generateCertificates(envelope.getString("ca_pem").byteInputStream())
            require(certificates.size == 1) { "one site CA required" }
            val ca = certificates.single() as X509Certificate
            require(ca.basicConstraints >= 0) { "site CA required" }
            ca.checkValidity()
            val rows = envelope.getJSONArray("robots")
            require(rows.length() in 1..60) { "robots required" }
            val robots = (0 until rows.length()).map { index ->
                val row = rows.getJSONObject(index)
                require(row.keys().asSequence().toSet() == setOf("robot_id", "tls_host", "port", "credential")) { "invalid robot" }
                require(listOf("robot_id", "tls_host", "credential").all { row.opt(it) is String } && row.opt("port") is Int) { "invalid robot field type" }
                val target = RobotTarget(row.getString("robot_id"), row.getString("tls_host"), row.getInt("port"), row.getString("credential"))
                require(target.port in 1..65535 && target.credential.length in 16..1024) { "invalid robot credential or port" }
                require(policy.permits(target.id, "_rosy._tcp", target.host, true)) { "robot outside development scope" }
                target
            }
            require(robots.map { it.id }.distinct().size == robots.size && robots.map { it.host }.distinct().size == robots.size) { "duplicate robot" }
            return PilotProfile(policy, ca, robots)
        }
    }
}
