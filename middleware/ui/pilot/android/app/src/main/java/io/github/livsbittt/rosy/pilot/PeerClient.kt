package io.github.livsbittt.rosy.pilot

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
/** D-483: the robot-screen approval code did not match; null when the receiver gave no count. */
class PeerCodeWrong(val remaining: Int?) : IOException("approval code did not match")
data class PeerPending(val code: String, val receiverId: String, val expiresAt: Instant)

/** One selected endpoint, one cancelable approval/renewal; never retries a positive session POST. */
class PeerClient internal constructor(private val candidate: Candidate, private val store: CandidateStore,
    private val signer: PeerSigner, private val vault: PeerRelationshipVault,
    private val current: () -> Boolean = { true }, private val now: () -> Instant = Instant::now,
    private val baseClient: OkHttpClient = lobbyClient(candidate), private val pause: ((Long) -> Unit)? = null,
    private val monotonic: () -> Long = System::nanoTime) {
    private val lock = Object()
    private var closed = false
    private var active: Call? = null
    private var requestId: String? = null
    private var requestSecret: String? = null
    private var approved = false
    private val origin = PeerRelationshipVault.origin(candidate)
    private var client = baseClient.newBuilder().retryOnConnectionFailure(false).cache(null).build()
    private var trusted = true
    private var firstContact: PeerFirstContact? = null
    private var receiverId = candidate.robotId
    private val clients = mutableSetOf(client)
    fun close() { synchronized(lock) { closed = true; active?.cancel(); lock.notifyAll() } }
    private fun alive(): Boolean = synchronized(lock) { !closed && current() && store.matches(candidate, receiverId) }
    private fun checkAlive() { if (!alive()) throw PeerCanceled() }

    /** null means an authenticated HTTPS server returned actual identity404, so legacy code UI may remain. */
    fun connect(onPending: (PeerPending) -> Unit, confirmCa: (PeerCaOffer) -> Boolean): LobbySession? {
        val fence = vault.fence(candidate)
        val remembered = vault.read(candidate)
        try {
            if (remembered != null) {
                if (!remembered.validAt(now())) throw PeerApprovalExpired()
                require(remembered.clientId == signer.clientId && remembered.clientKeySha256 == PeerProof.fingerprint(signer.publicKey)) { "client identity unavailable" }
                client = PeerTls.pinned(client, remembered.caPem); clients.add(client)
            }
            var identity: JSONObject
            try { identity = call("/identity", "GET") }
            catch (error: PeerRefused) { if (error.status == 404 && remembered == null) return null else throw error }
            catch (error: javax.net.ssl.SSLException) {
                if (remembered != null) throw error
                firstContact = PeerFirstContact(); trusted = false
                client = PeerTls.firstContact(client, firstContact!!); clients.add(client)
                identity = call("/identity", "GET")
            }
            receiverId = string(identity, "receiver_id", 64)
            require(Regex("rosy_(?:0[1-9]|[1-9][0-9]*)").matches(receiverId))
            require(candidate.robotId.isEmpty() || receiverId == candidate.robotId)
            val receiverKey = string(identity, "receiver_public_key", 256)
            val receiverFingerprint = PeerProof.fingerprint(receiverKey)
            require(receiverFingerprint == string(identity, "receiver_key_sha256", 64))
            if (remembered != null && (remembered.receiverId != receiverId || remembered.receiverPublicKey != receiverKey)) throw PeerKeyChanged()
            checkAlive()
            // 저장 세션 재사용(2026-10-06 사용자 결정): 발급받은 세션은 자연 만료까지 재연결마다 그대로 쓴다.
            // whoami·system/info 로 살아있음을 확인하고, 못 쓰면 지우고 새 발급 경로로 내려간다.
            if (remembered != null) {
                val stored = vault.readSession(candidate)
                if (stored != null && stored.relationshipId == remembered.id && stored.role == remembered.role
                    && stored.expiresAt.isAfter(now().plusSeconds(60))) {
                    val reused = runCatching {
                        val accessToken = stored.token
                        val who = call("/api/v1/auth/whoami", "GET", bearer = accessToken)
                        require(string(who, "role", 32) == remembered.role)
                        val info = call("/api/v1/system/info", "GET", bearer = accessToken)
                        require(string(info, "robot_id", 64) == remembered.receiverId)
                        LobbySession(RobotTarget(remembered.receiverId, candidate.host, candidate.port, accessToken), true,
                            stored.expiresAt, candidate, store, remembered.caPem, remembered)
                    }.getOrNull()
                    if (reused != null) { checkAlive(); return reused }
                    runCatching { vault.eraseSession(candidate) }
                }
            }
            val bootstrap = if (!trusted) PeerCaOffer(string(identity, "tls_ca_pem", 8192), string(identity, "tls_ca_sha256", 64),
                string(identity, "tls_hostname", 253)).also { PeerTls.bind(it, firstContact?.leaf ?: error("first-contact leaf unavailable"), candidate.host) } else null
            var caPem = remembered?.caPem
            val relationship = remembered ?: run {
                val fields = JSONObject().put("receiver_id", receiverId).put("receiver_key_sha256", receiverFingerprint)
                    .put("client_id", signer.clientId).put("client_public_key", signer.publicKey).put("label", "Rosy Pilot")
                    .put("role", "operator").put("nonce", ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) })
                val created = call("/requests", "POST", signed("request", fields))
                requestId = identifier(created, "request_id"); requestSecret = string(created, "request_secret", 43)
                require(Regex("[A-Za-z0-9_-]{43}").matches(requestSecret!!))
                val expires = expiry(created, "expires_at"); require(expires > now())
                val deadline = minOf(expires, now().plusSeconds(300))
                val started = monotonic()
                var state = created
                while (true) {
                    checkAlive(); require(identifier(state, "request_id") == requestId && state.get("paired") == false)
                    if (now() >= deadline || monotonic() - started >= 300_000_000_000L) throw PeerApprovalTimeout()
                    when (string(state, "state", 16)) {
                        "approved" -> { approved = true; if (state.get("authorization_available") != true) throw PeerRefused(409); break }
                        "pending" -> {
                            val code = string(state, "display_code", 4); require(Regex("[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}").matches(code))
                            onPending(PeerPending(code, receiverId, deadline)); require(now() < deadline)
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
                    val offer = requireNotNull(bootstrap)
                    require(confirmCa(offer)) { "receiver fingerprint was not matched" }
                    checkAlive(); caPem = offer.pem
                    client = PeerTls.pinned(baseClient.newBuilder().retryOnConnectionFailure(false).cache(null).build(), caPem); clients.add(client)
                    trusted = true
                }
                PeerRelationship(origin, receiverId, receiverKey, signer.clientId, PeerProof.fingerprint(signer.publicKey), requestId!!,
                    "operator", integer(state, "generation"), persistent, authorizationExpiry, caPem)
            }
            require(relationship.validAt(now())); require(trusted)
            // Preserve the authenticated decision before a transient challenge/session failure.
            // A stored approval never permits a session without the fresh signed challenge below.
            if (remembered == null) synchronized(lock) { checkAlive(); vault.remember(candidate, relationship, fence) }
            val challenge = call("/relationships/${relationship.id}/challenge", "POST", JSONObject())
            val fields = challenge.getJSONObject("fields")
            val expected = setOf("relationship_id", "challenge_id", "nonce", "receiver_id", "receiver_key_sha256", "client_id", "client_key_sha256", "role", "generation", "expires_at")
            require(fields.keys().asSequence().toSet() == expected)
            require(identifier(fields, "relationship_id") == relationship.id && identifier(fields, "challenge_id").isNotEmpty())
            require(string(fields, "receiver_id", 64) == relationship.receiverId && string(fields, "receiver_key_sha256", 64) == receiverFingerprint)
            require(string(fields, "client_id", 64) == signer.clientId && string(fields, "client_key_sha256", 64) == relationship.clientKeySha256)
            require(string(fields, "role", 16) == relationship.role && integer(fields, "generation") == relationship.generation)
            require(Regex("[0-9a-f]{64}").matches(string(fields, "nonce", 64)))
            val nonceExpiry = expiry(fields, "expires_at"); require(nonceExpiry > now() && nonceExpiry <= now().plusSeconds(65))
            PeerProof.verify(receiverKey, "receiver-challenge", fields, string(challenge, "receiver_signature", 128))
            checkAlive()
            val issued = call("/relationships/${relationship.id}/session", "POST", signed("session-request", fields))
            string(issued, "id", 128)
            val accessToken = string(issued, "token", 128); require(accessToken.length >= 16 && string(issued, "role", 16) == relationship.role)
            val sessionExpiry = expiry(issued, "expires_at"); require(sessionExpiry > now() && sessionExpiry <= now().plusSeconds(3605))
            relationship.authorizationExpiresAt?.let { require(sessionExpiry <= it) }
            checkAlive()
            val who = call("/api/v1/auth/whoami", "GET", bearer = accessToken)
            require(string(who, "role", 32) == relationship.role)
            val info = call("/api/v1/system/info", "GET", bearer = accessToken); require(string(info, "robot_id", 64) == receiverId)
            checkAlive()
            // 발급 세션을 저장해 다음 재연결에서 재사용한다(저장 실패가 연결을 깨지 않게 감싼다).
            runCatching { vault.rememberSession(candidate, PeerSessionRecord(origin, relationship.id, accessToken, relationship.role, sessionExpiry)) }
            return LobbySession(RobotTarget(receiverId, candidate.host, candidate.port, accessToken), true, sessionExpiry, candidate, store, caPem, relationship)
        } finally {
            if (!approved && requestId != null && requestSecret != null) cleanupCancel()
            clients.forEach { it.connectionPool.evictAll(); it.dispatcher.executorService.shutdown() }
        }
    }
    /**
     * D-483: send the approval code the receiver's LCD shows for the pending request.
     * The status poll in [connect] then sees the approval (or a console approval that won first).
     * 404 is an older CORE without the route ([PeerRefused]); a wrong code is [PeerCodeWrong].
     */
    fun confirm(code: String) {
        require(APPROVAL_CODE.matches(code)) { "approval code format" }
        val (id, secret) = synchronized(lock) { checkAlive(); (requestId ?: throw PeerCanceled()) to (requestSecret ?: throw PeerCanceled()) }
        val request = Request.Builder().url(origin + path("/requests/$id/confirm")).header("Cache-Control", "no-store")
            .header("X-Request-Secret", secret).post(oneShot(JSONObject().put("approval_code", code))).build()
        client.newBuilder().callTimeout(10, TimeUnit.SECONDS).build().newCall(request).execute().use { response ->
            if (response.code == 400) {
                val remaining = runCatching {
                    val body = response.body?.byteStream()?.let { MainActivity.readLimited(it, 4096).toString(Charsets.UTF_8) }
                    JSONObject(body ?: "{}").getJSONObject("detail").getInt("remaining_attempts").takeIf { it in 0..5 }
                }.getOrNull()
                throw PeerCodeWrong(remaining)
            }
            if (!response.isSuccessful) throw PeerRefused(response.code)
        }
    }
    private fun signed(context: String, fields: JSONObject) = JSONObject().put("fields", fields).put("signature", signer.sign(context, fields))
    private fun waitPoll() {
        if (pause != null) pause.invoke(2000) else synchronized(lock) { if (!closed) lock.wait(2000) }
        checkAlive()
    }
    private fun path(path: String) = if (path.startsWith("/api/")) path else "/api/v1/auth/peer-pairing$path"
    private fun call(path: String, method: String, body: JSONObject? = null, secret: String? = null, bearer: String? = null): JSONObject {
        checkAlive()
        if (!trusted) require(bearer == null && (path == "/identity" || path == "/requests" || Regex("/requests/[A-Za-z0-9_-]{32}").matches(path)))
        val builder = Request.Builder().url(origin + path(path)).header("Cache-Control", "no-store")
        if (secret != null) builder.header("X-Request-Secret", secret)
        if (bearer != null) { require(trusted); builder.header("Authorization", "Bearer $bearer") }
        val request = builder.method(method, if (method == "POST") oneShot(body ?: JSONObject()) else null).build()
        val activeCall = client.newCall(request)
        synchronized(lock) { checkAlive(); active = activeCall }
        try {
            activeCall.execute().use { response ->
                if (!response.isSuccessful) throw PeerRefused(response.code)
                val result = JSONObject(response.body?.byteStream()?.let { MainActivity.readLimited(it, 16384).toString(Charsets.UTF_8) } ?: error("empty receiver response"))
                checkAlive(); return result
            }
        } finally { synchronized(lock) { if (active === activeCall) active = null } }
    }
    private fun cleanupCancel() {
        // A lost/unreceived creation reply has no usable secret; its bounded server TTL remains authoritative.
        if (!store.matches(candidate, receiverId)) return
        runCatching { client.newBuilder().callTimeout(2, TimeUnit.SECONDS).build().newCall(Request.Builder()
            .url(origin + path("/requests/$requestId")).header("X-Request-Secret", requestSecret!!).delete().build()).execute().close() }
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
    companion object {
        /** D-483: six characters of the receiver's code alphabet, upper case. */
        val APPROVAL_CODE = Regex("[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{6}")
    }
}
