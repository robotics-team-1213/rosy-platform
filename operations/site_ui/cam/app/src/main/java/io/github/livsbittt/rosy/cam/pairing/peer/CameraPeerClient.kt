package io.github.livsbittt.rosy.cam.pairing.peer

import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.settings.SiteLink
import okhttp3.Dns
import java.net.InetAddress
import java.net.UnknownHostException
import java.security.cert.X509Certificate
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject
import java.io.IOException
import java.security.SecureRandom
import java.time.Instant
import java.time.OffsetDateTime
import java.util.concurrent.TimeUnit

class PeerRefused(val status: Int) : IOException("receiver approval unavailable")
class PeerKeyChanged : IOException("receiver identity changed")
class PeerCanceled : IOException("receiver request canceled")
class PeerApprovalExpired : IOException("approval usage expired; local record retained")
class PeerApprovalTimeout : IOException("receiver approval timed out")
data class CameraPending(val code: String, val receiverId: String, val expiresAt: Instant)

/** One selected endpoint, one cancelable approval/renewal; never retries a positive session POST. */
class CameraPeerClient internal constructor(private val candidate: PairableSite,
    private val signer: CameraSigner, private val vault: CameraRelationshipVault,
    private val current: () -> Boolean = { true }, private val now: () -> Instant = Instant::now,
    private val baseClient: OkHttpClient = cameraPeerHttp(candidate), private val pause: ((Long) -> Unit)? = null,
    private val monotonic: () -> Long = System::nanoTime) {
    private val lock = Object()
    private var closed = false
    private var active: Call? = null
    private var requestId: String? = null
    private var requestSecret: String? = null
    private var approved = false
    private val origin = CameraRelationshipVault.origin(candidate)
    private val attemptFence = vault.fence(candidate)
    private var client = baseClient.newBuilder().retryOnConnectionFailure(false).cache(null).build()
    private var trusted = true
    private var firstContact: CameraFirstContact? = null
    private var receiverId = ""
    private var identityLeaf: X509Certificate? = null
    private val clients = mutableSetOf(client)
    fun close() { synchronized(lock) { closed = true; active?.cancel(); lock.notifyAll() } }
    private fun alive(): Boolean = synchronized(lock) { !closed && current() && vault.fence(candidate) == attemptFence }
    private fun checkAlive() { if (!alive()) throw PeerCanceled() }

    /** Explicit v2 discovery only: a failed v2 transaction never downgrades to the legacy flow. */
    fun connect(onPending: (CameraPending) -> Unit, confirmCa: (CameraCaOffer) -> Boolean): CameraConnection {
        val fence = attemptFence
        val remembered = vault.read(candidate)
        try {
            if (remembered != null) {
                if (!remembered.validAt(now())) throw PeerApprovalExpired()
                require(remembered.clientId == signer.clientId && remembered.clientKeySha256 == CameraProof.fingerprint(signer.publicKey)) { "client identity unavailable" }
                client = CameraTls.pinned(client, remembered.caPem); clients.add(client)
            }
            var identity: JSONObject
            try { identity = call("/identity", "GET") }
            catch (error: javax.net.ssl.SSLException) {
                if (remembered != null) throw error
                firstContact = CameraFirstContact(); trusted = false
                client = CameraTls.firstContact(client, firstContact!!); clients.add(client)
                identity = call("/identity", "GET")
            }
            profile(identity)
            receiverId = string(identity, "receiver_id", 64)
            require(Regex("fleet-[0-9a-f]{32}").matches(receiverId))
            val receiverKey = string(identity, "receiver_public_key", 256)
            val receiverFingerprint = CameraProof.fingerprint(receiverKey)
            require(receiverFingerprint == string(identity, "receiver_key_sha256", 64))
            require(receiverId == "fleet-" + receiverFingerprint.take(32))
            if (remembered != null && (remembered.receiverId != receiverId || remembered.receiverPublicKey != receiverKey)) throw PeerKeyChanged()
            checkAlive()
            val bootstrap = CameraCaOffer(string(identity, "tls_ca_pem", 8192), string(identity, "tls_ca_sha256", 64),
                string(identity, "tls_hostname", 253)).also {
                    CameraTls.bind(it, identityLeaf ?: firstContact?.leaf ?: error("identity leaf unavailable"), candidate.tlsHost)
                    if (remembered != null) require(CameraProof.hash(CameraTls.ca(remembered.caPem).encoded) == it.sha256) { "receiver CA changed" }
                }
            var caPem = remembered?.caPem ?: bootstrap.pem
            val relationship = remembered ?: run {
                val fields = profileFields().put("receiver_id", receiverId).put("receiver_key_sha256", receiverFingerprint)
                    .put("client_id", signer.clientId).put("client_public_key", signer.publicKey).put("label", "Rosy Cam")
                    .put("nonce", ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) })
                val created = call("/requests", "POST", signed("request", fields))
                requestId = identifier(created, "request_id"); requestSecret = string(created, "request_secret", 43)
                require(Regex("[A-Za-z0-9_-]{43}").matches(requestSecret!!))
                val expires = expiry(created, "expires_at"); require(expires > now())
                val deadline = minOf(expires, now().plusSeconds(300))
                val started = monotonic()
                var state = created
                while (true) {
                    checkAlive(); profile(state); require(identifier(state, "request_id") == requestId && state.get("credential_issued") == false)
                    if (now() >= deadline || monotonic() - started >= 300_000_000_000L) throw PeerApprovalTimeout()
                    when (string(state, "state", 16)) {
                        "approved" -> { approved = true; if (state.get("authorization_available") != true) throw PeerRefused(409); break }
                        "pending" -> {
                            val code = string(state, "display_code", 4); require(Regex("[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}").matches(code))
                            onPending(CameraPending(code, receiverId, deadline)); require(now() < deadline)
                            waitPoll(); state = call("/requests/$requestId", "GET", secret = requestSecret)
                        }
                        else -> throw IOException("receiver did not approve request")
                    }
                }
                require(identifier(state, "relationship_id") == requestId)
                val persistent = state.get("persistent") as? Boolean ?: throw IllegalArgumentException("approval lifetime unavailable")
                val authorizationExpiry = if (state.isNull("authorization_expires_at")) null else expiry(state, "authorization_expires_at")
                require(persistent == (authorizationExpiry == null))
                if (!trusted) {
                    val offer = bootstrap
                    require(confirmCa(offer)) { "receiver fingerprint was not matched" }
                    checkAlive(); caPem = offer.pem
                    client = CameraTls.pinned(baseClient.newBuilder().retryOnConnectionFailure(false).cache(null).build(), caPem); clients.add(client)
                    trusted = true
                }
                CameraRelationship(origin, receiverId, receiverKey, signer.clientId, CameraProof.fingerprint(signer.publicKey), requestId!!,
                    integer(state, "generation"), source(state), persistent, authorizationExpiry, caPem)
            }
            require(relationship.validAt(now())); require(trusted)
            client = CameraTls.pinned(baseClient, caPem); clients.add(client)
            // Preserve the authenticated decision before a transient challenge/session failure.
            // A stored approval never permits a session without the fresh signed challenge below.
            if (remembered == null) synchronized(lock) { checkAlive(); vault.remember(candidate, relationship, fence) }
            val challenge = call("/challenge", "POST", JSONObject().put("relationship_id", relationship.id).put("generation", relationship.generation))
            val fields = challenge.getJSONObject("fields")
            val expected = setOf("relationship_id", "challenge_id", "nonce", "receiver_id", "receiver_key_sha256", "client_id", "client_key_sha256", "source_id", "generation", "expires_at", "profile", "audience", "device_kind", "source_role")
            require(fields.keys().asSequence().toSet() == expected); profile(fields)
            require(identifier(fields, "relationship_id") == relationship.id && identifier(fields, "challenge_id").isNotEmpty())
            require(string(fields, "receiver_id", 64) == relationship.receiverId && string(fields, "receiver_key_sha256", 64) == receiverFingerprint)
            require(string(fields, "client_id", 64) == signer.clientId && string(fields, "client_key_sha256", 64) == relationship.clientKeySha256)
            require(source(fields) == relationship.sourceId && integer(fields, "generation") == relationship.generation)
            require(Regex("[0-9a-f]{64}").matches(string(fields, "nonce", 64)))
            val nonceExpiry = expiry(fields, "expires_at"); require(nonceExpiry > now() && nonceExpiry <= now().plusSeconds(65))
            CameraProof.verify(receiverKey, "receiver-challenge", fields, string(challenge, "receiver_signature", 128))
            checkAlive()
            val issued = call("/session", "POST", signed("session-request", fields))
            profile(issued)
            require(identifier(issued, "relationship_id") == relationship.id && integer(issued, "generation") == relationship.generation)
            val credentialId = string(issued, "credential_id", 64)
            require(Regex("cam-peer-[A-Za-z0-9_-]{24}").matches(credentialId))
            val accessToken = string(issued, "token", 128)
            require(Regex("[A-Za-z0-9_-]{16,128}").matches(accessToken) && string(issued, "role", 32) == SiteLink.ROLE)
            require(source(issued) == relationship.sourceId)
            val sessionExpiry = expiry(issued, "expires_at")
            require(sessionExpiry > now() && sessionExpiry <= now().plusSeconds(180L * 86400 + 5))
            relationship.authorizationExpiresAt?.let { require(sessionExpiry <= it) }
            checkAlive(); require(vault.fence(candidate) == fence)
            val ca = CameraTls.ca(caPem)
            val pin = "sha256/" + java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(java.security.MessageDigest.getInstance("SHA-256").digest(ca.encoded))
            val link = SiteLink(candidate.serviceName, candidate.tlsHost, candidate.port, pin, accessToken, relationship.sourceId,
                true, credentialId = credentialId, expiresAt = sessionExpiry.toString())
            require(SiteLink.validate(link) == null)
            return CameraConnection(link, relationship, fence)
        } finally {
            if (!approved && requestId != null && requestSecret != null) cleanupCancel()
            clients.forEach { it.connectionPool.evictAll(); it.dispatcher.executorService.shutdown() }
        }
    }
    private fun profileFields() = JSONObject().put("profile", "rosy.camera-peer/1").put("audience", "fleet-camera-ingest")
        .put("device_kind", "overhead-camera").put("source_role", "camera")
    private fun profile(row: JSONObject) {
        val required = profileFields()
        required.keys().forEach { require(row.get(it) == required.get(it)) { "camera profile mismatch" } }
    }
    private fun source(row: JSONObject) = string(row, "source_id", 32).also { require(Regex("[A-Za-z0-9_-]{1,32}").matches(it)) }
    private fun readBounded(input: java.io.InputStream): ByteArray {
        val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(2048)
        while (true) { val count = input.read(buffer); if (count < 0) break; require(output.size() + count <= 16384); output.write(buffer, 0, count) }
        return output.toByteArray()
    }
    private fun signed(context: String, fields: JSONObject) = JSONObject().put("fields", fields).put("signature", signer.sign(context, fields))
    private fun waitPoll() {
        if (pause != null) pause.invoke(2000) else synchronized(lock) { if (!closed) lock.wait(2000) }
        checkAlive()
    }
    private fun path(path: String) = if (path.startsWith("/api/")) path else "/api/fleet/pairing/v2$path"
    private fun call(path: String, method: String, body: JSONObject? = null, secret: String? = null): JSONObject {
        checkAlive()
        if (!trusted) require((path == "/identity" || path == "/requests" || Regex("/requests/[A-Za-z0-9_-]{32}").matches(path)))
        val builder = Request.Builder().url(origin + path(path)).header("Cache-Control", "no-store")
        if (secret != null) builder.header("Authorization", "Bearer $secret")
        val request = builder.method(method, if (method == "POST") oneShot(body ?: JSONObject()) else null).build()
        val activeCall = client.newCall(request)
        synchronized(lock) { checkAlive(); active = activeCall }
        try {
            activeCall.execute().use { response ->
                if (!response.isSuccessful) throw PeerRefused(response.code)
                if (path == "/identity") identityLeaf = response.handshake?.peerCertificates?.firstOrNull() as? X509Certificate
                val bytes = response.body?.byteStream()?.use { readBounded(it) } ?: error("empty receiver response")
                require(bytes.size <= 16384)
                val result = JSONObject(bytes.toString(Charsets.UTF_8))
                checkAlive(); return result
            }
        } finally { synchronized(lock) { if (active === activeCall) active = null } }
    }
    private fun cleanupCancel() {
        // A lost/unreceived creation reply has no usable secret; its bounded server TTL remains authoritative.
        runCatching { client.newBuilder().callTimeout(2, TimeUnit.SECONDS).build().newCall(Request.Builder()
            .url(origin + path("/requests/$requestId/cancel")).header("Authorization", "Bearer ${requestSecret!!}").post(oneShot(JSONObject())).build()).execute().close() }
    }
    private fun oneShot(body: JSONObject): RequestBody {
        val bytes = body.toString().toByteArray(Charsets.UTF_8); require(bytes.size <= 4096)
        return object : RequestBody() {
            override fun contentType() = "application/json".toMediaType()
            override fun contentLength() = bytes.size.toLong()
            override fun isOneShot() = true
            override fun writeTo(sink: okio.BufferedSink) { sink.write(bytes) }
        }
    }
    private fun string(row: JSONObject, key: String, max: Int): String = (row.get(key) as? String)?.also { require(it.length in 1..max) } ?: throw IllegalArgumentException("invalid receiver field")
    private fun identifier(row: JSONObject, key: String) = string(row, key, 32).also { require(Regex("[A-Za-z0-9_-]{32}").matches(it)) }
    private fun integer(row: JSONObject, key: String): Long {
        val raw = row.get(key); require(raw is Int || raw is Long)
        return (raw as Number).toLong().also { require(it >= 0) }
    }
    private fun expiry(row: JSONObject, key: String) = OffsetDateTime.parse(string(row, key, 64)).toInstant()
}

data class CameraConnection(val link: SiteLink, val relationship: CameraRelationship, val fence: String)

internal fun cameraPeerHttp(site: PairableSite): OkHttpClient {
    CameraRelationshipVault.origin(site)
    return OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).readTimeout(8, TimeUnit.SECONDS).callTimeout(10, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false).followRedirects(false).followSslRedirects(false).cache(null)
        .dns(object : Dns {
            override fun lookup(hostname: String): List<InetAddress> {
                val address = site.address
                if (hostname != site.tlsHost || address == null || !SiteLink.isIpLiteral(address)) throw UnknownHostException("selected camera receiver unavailable")
                return listOf(InetAddress.getByName(address))
            }
        }).build()
}
