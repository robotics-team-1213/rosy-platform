package io.github.livsbittt.rosy.pilot

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject
import java.time.Instant
import java.util.concurrent.TimeUnit

interface PilotConnection {
    val target: RobotTarget
    val secure: Boolean
    fun authorized(): Boolean
    fun client(): OkHttpClient
    fun invalidateCredential() = Unit
}

class ScopedProfileConnection(private val profile: PilotProfile, override val target: RobotTarget,
    private val candidates: CandidateStore) : PilotConnection {
    override val secure = true
    override fun authorized() = profile.authorized(target)
    override fun client() = profile.client(target, candidates)
}

/** HTTP approval remains bound to the selected IP. A changed address requires a fresh session. */
class LobbySession(override val target: RobotTarget, override val secure: Boolean,
    val expiresAt: Instant, private val candidate: Candidate, private val store: CandidateStore) : PilotConnection {
    var onInvalidated: () -> Unit = {}
    override fun invalidateCredential() { onInvalidated() }
    override fun authorized(): Boolean = Instant.now() < expiresAt && runCatching {
        store.matches(candidate, target.id)
    }.getOrDefault(false)
    override fun client(): OkHttpClient = lobbyClient(candidate) { authorized() }
}

fun lobbyClient(candidate: Candidate, allowed: () -> Boolean = { true }): OkHttpClient = OkHttpClient.Builder()
    .dns(object : okhttp3.Dns {
        override fun lookup(hostname: String): List<java.net.InetAddress> {
            check(allowed() && hostname == candidate.host) { "selected device changed" }
            return candidate.addresses.map { java.net.InetAddress.getByName(it) }
        }
    }).protocols(listOf(okhttp3.Protocol.HTTP_1_1)).followRedirects(false).followSslRedirects(false)
    .connectTimeout(5, TimeUnit.SECONDS).readTimeout(5, TimeUnit.SECONDS).callTimeout(8, TimeUnit.SECONDS).build()

data class LobbyOffer(val mode: String, val robotId: String, val legacy: Boolean = false)

object LobbyPairing {
    fun offer(candidate: Candidate): LobbyOffer {
        val client = lobbyClient(candidate)
        try {
            client.newCall(Request.Builder().url(url(candidate, "/api/v1/auth/connection")).build()).execute().use { response ->
                if (response.code == 404) return LobbyOffer("paired", candidate.robotId, legacy = true)
                check(response.isSuccessful) { "connection service unavailable" }
                val data = read(response)
                val mode = data.getString("mode"); val id = data.getString("robot_id")
                check(mode in listOf("paired", "development") && Regex("rosy_(?:0[1-9]|[1-9][0-9]*)").matches(id)) { "invalid connection offer" }
                check(data.getString("transport") == if (candidate.secure) "https" else "http") { "transport mismatch" }
                if (candidate.robotId.isNotEmpty()) check(candidate.robotId == id) { "robot identity mismatch" }
                return LobbyOffer(mode, id)
            }
        } finally { client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll() }
    }
    fun connect(candidate: Candidate, offer: LobbyOffer, store: CandidateStore, code: String? = null): LobbySession {
        val development = offer.mode == "development"
        val normalizedCode = if (!development) PairingCode.normalize(requireNotNull(code)) else null
        check(store.matches(candidate, offer.robotId)) { "selected device changed" }
        val client = lobbyClient(candidate)
        try {
            val path = if (development) "/api/v1/auth/development-session" else "/api/v1/auth/pair"
            val data = JSONObject().apply { if (!development) { put("code", normalizedCode); put("label", "Rosy Pilot") } }
            client.newCall(Request.Builder().url(url(candidate, path)).post(data.toString().toRequestBody("application/json".toMediaType())).build())
                .execute().use { response ->
                    android.util.Log.i("RosyPilot", "Pair approval HTTP ${response.code}; development=$development")
                    if (!response.isSuccessful) throw PairingRejected(response.code)
                    val body = read(response); val credential = body.getString("token")
                    check(credential.length in 16..1024) { "invalid session credential" }
                    val expiry = if (body.isNull("expires_at")) { if (development) Instant.now().plusSeconds(3600) else Instant.MAX }
                        else java.time.OffsetDateTime.parse(body.getString("expires_at")).toInstant()
                    check(expiry > Instant.now()) { "session expired" }
                    val id = if (offer.legacy) {
                        check(store.matches(candidate, offer.robotId)) { "selected device changed" }
                        client.newCall(Request.Builder().url(url(candidate, "/api/v1/system/info"))
                            .header("Authorization", "Bearer $credential").build()).execute().use { identity ->
                                check(identity.isSuccessful) { "identity unavailable" }
                                read(identity).getString("robot_id").also {
                                    check(Regex("rosy_(?:0[1-9]|[1-9][0-9]*)").matches(it)) { "invalid robot identity" }
                                    if (offer.robotId.isNotEmpty()) check(it == offer.robotId) { "robot identity mismatch" }
                                }
                            }
                    } else offer.robotId
                    check(store.matches(candidate, id)) { "selected device changed" }
                    return LobbySession(RobotTarget(id, candidate.host, candidate.port, credential), candidate.secure, expiry, candidate, store)
                }
        } finally { client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll() }
    }
    fun reuse(session: LobbySession): Boolean {
        check(session.authorized()) { "selected device changed" }
        val client = session.client()
        try {
            val target = session.target
            client.newCall(Request.Builder().url("${if (session.secure) "https" else "http"}://${target.host}:${target.port}/api/v1/auth/whoami")
                .header("Authorization", "Bearer ${target.credential}").build()).execute().use { response ->
                if (response.code in listOf(401, 403)) return false
                check(response.isSuccessful) { "session verification unavailable" }
                return read(response).optString("role") in listOf("operator", "administrator")
            }
        } finally { client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll() }
    }
    private fun url(candidate: Candidate, path: String) = "${if (candidate.secure) "https" else "http"}://${candidate.host}:${candidate.port}$path"
    private fun read(response: okhttp3.Response): JSONObject = JSONObject(
        response.body?.byteStream()?.let { MainActivity.readLimited(it, 65536).toString(Charsets.UTF_8) } ?: error("empty connection response"))
}
