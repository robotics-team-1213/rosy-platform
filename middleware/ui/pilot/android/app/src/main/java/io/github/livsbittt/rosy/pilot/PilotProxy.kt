package io.github.livsbittt.rosy.pilot

import fi.iki.elonen.NanoHTTPD
import fi.iki.elonen.NanoWSD
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.io.IOException
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.SynchronousQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

/** Private loopback origin relays the existing PWA. TLS always checks the scoped DNS identity. */
class PilotProxy(private val connection: PilotConnection, private val assets: BundledAssets? = null,
    private val failure: (String) -> Unit, private val recovery: () -> Unit = {}) : NanoWSD("127.0.0.1", 0) {
    constructor(profile: PilotProfile, target: RobotTarget, candidates: CandidateStore, failure: (String) -> Unit,
        recovery: () -> Unit = {}) :
        this(ScopedProfileConnection(profile, target, candidates), null, failure, recovery)
    private val target = connection.target
    private val scheme = if (connection.secure) "https" else "http"
    val capability = ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
    val origin get() = "http://127.0.0.1:$listeningPort"
    private val client = connection.client()
    @Volatile private var identityVerified = false
    /** 한 번 실패를 알렸으면 다음 성공 응답에서 회복을 알린다 — 오류 문구가 회복 뒤에도 남지 않게. */
    @Volatile private var failureReported = false
    private val sockets = ConcurrentHashMap.newKeySet<Relay>()
    private val clients = ConcurrentHashMap.newKeySet<NanoHTTPD.ClientHandler>()
    private val executor = ThreadPoolExecutor(0, 12, 30, TimeUnit.SECONDS, SynchronousQueue<Runnable>())
    init {
        setAsyncRunner(object : NanoHTTPD.AsyncRunner {
            override fun closeAll() { clients.toList().forEach { it.close() }; clients.clear(); executor.shutdownNow() }
            override fun closed(handler: NanoHTTPD.ClientHandler) { clients.remove(handler) }
            override fun exec(handler: NanoHTTPD.ClientHandler) {
                clients.add(handler)
                try { executor.execute(handler) } catch (_: java.util.concurrent.RejectedExecutionException) { clients.remove(handler); handler.close() }
            }
        })
    }
    override fun serve(session: IHTTPSession): Response {
        val requiresApproval = session.uri.startsWith("/api/v1/") || session.uri.startsWith("/ws/") || session.uri == "/pilot/bootstrap.js"
        if ((requiresApproval && !connection.authorized()) || !ProxyGuard("127.0.0.1:$listeningPort", capability).permits(session.headers) ||
            !ProxyGuard.allowedPath(session.uri)) return newFixedLengthResponse(Response.Status.FORBIDDEN, "text/plain", "Connection unavailable")
        return super.serve(session)
    }
    override fun serveHttp(session: IHTTPSession): Response {
        if (session.uri == "/pilot/bootstrap.js") return reply(200, "application/javascript", "document.documentElement.dataset.pilotShell='android';sessionStorage.setItem('rosy.pilot.token',${JSONObject.quote(target.credential)});".toByteArray())
        if (session.uri.endsWith("/sw.js")) return reply(404, "text/plain", ByteArray(0))
        val asset = BundledPath.asset(session.uri)
        if (asset != null) {
            if (session.method !in listOf(Method.GET, Method.HEAD)) return reply(405, "text/plain", ByteArray(0))
            var bytes = assets?.read(asset) ?: return reply(404, "text/plain", "Bundled screen unavailable".toByteArray())
            if (asset == "pilot/index.html") bytes = bytes.toString(Charsets.UTF_8)
                .replace("<head>", "<head><script src=\"/pilot/bootstrap.js\"></script>").toByteArray()
            return reply(200, BundledPath.mime(asset), bytes)
        }
        if (!session.uri.startsWith("/api/v1/")) return reply(404, "text/plain", ByteArray(0))
        try {
            val length = session.headers["content-length"]?.toLongOrNull() ?: 0L
            if (length !in 0..262144 || session.headers.containsKey("transfer-encoding")) return reply(413, "text/plain", ByteArray(0))
            val method = session.method.name
            if (method !in setOf("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")) return reply(405, "text/plain", ByteArray(0))
            val body = if (method in setOf("POST", "PUT", "PATCH", "DELETE")) {
                val data = ByteArray(length.toInt())
                var read = 0
                while (read < data.size) { val count = session.inputStream.read(data, read, data.size - read); if (count < 0) break; read += count }
                if (read != length.toInt()) return reply(400, "text/plain", ByteArray(0))
                data.toRequestBody(session.headers["content-type"]?.toMediaTypeOrNull())
            } else null
            val query = session.queryParameterString?.let { "?$it" }.orEmpty()
            // Browser tokens, cookies and headers cannot choose or authorize a different endpoint.
            val request = Request.Builder().url("$scheme://${target.host}:${target.port}${session.uri}$query")
                .method(method, body).apply {
                    if (session.uri.startsWith("/api/v1/")) session.headers["authorization"]?.let { header("Authorization", it) }
                    session.headers["range"]?.let { header("Range", it) }
                }.build()
            val response = client.newCall(request).execute()
            var streaming = false
            try {
                if (failureReported) { failureReported = false; recovery() }
                if ((response.code == 401 && session.headers["authorization"] == "Bearer ${target.credential}") ||
                    (response.isSuccessful && session.uri == "/api/v1/auth/logout")) connection.invalidateCredential()
                if (response.isRedirect) return reply(502, "text/plain", "Redirect refused".toByteArray())
                val mime = response.header("Content-Type") ?: "application/octet-stream"
                if (session.uri.startsWith("/api/v1/") && (mime.startsWith("video/") || mime.startsWith("multipart/x-mixed-replace") || mime.startsWith("application/octet-stream") || mime.startsWith("application/x-tar"))) {
                    val length = response.body?.contentLength() ?: 0
                    if (length > 256L * 1024 * 1024) return reply(413, "text/plain", "Response too large".toByteArray())
                    val input = response.body?.byteStream() ?: ByteArray(0).inputStream()
                    val bounded = object : java.io.FilterInputStream(input) {
                        private var read = 0L
                        private fun count(value: Int): Int {
                            if (value > 0) read += value
                            if (read > 256L * 1024 * 1024) { close(); throw IOException("download too large") }
                            return value
                        }
                        override fun read() = super.read().also { if (it >= 0) count(1) }
                        override fun read(bytes: ByteArray, offset: Int, size: Int) = count(super.read(bytes, offset, size))
                        override fun close() { super.close(); response.close() }
                    }
                    val status = status(response.code)
                    val result = if (length >= 0) newFixedLengthResponse(status, mime, bounded, length)
                        else newChunkedResponse(status, mime, bounded)
                    response.header("Content-Range")?.let { result.addHeader("Content-Range", it) }
                    forwardRosyHeaders(response, result)
                    streaming = true
                    return secure(result)
                }
                val source = response.body?.byteStream()
                var bytes = source?.let { MainActivity.readLimited(it, 8 * 1024 * 1024) } ?: ByteArray(0)
                if (mime.startsWith("text/html")) {
                    bytes = bytes.toString(Charsets.UTF_8).replace("<head>", "<head><script src=\"/pilot/bootstrap.js\"></script>").toByteArray()
                }
                return reply(response.code, mime, bytes).apply {
                    response.header("Content-Range")?.let { addHeader("Content-Range", it) }
                    forwardRosyHeaders(response, this)
                }
            } finally { if (!streaming) response.close() }
        } catch (_: Exception) {
            failureReported = true
            failure(LINK_LOST)
            return reply(502, "text/plain", "Trusted connection unavailable".toByteArray())
        }
    }
    private fun status(code: Int) = object : Response.IStatus {
            override fun getRequestStatus() = code
            override fun getDescription() = Response.Status.lookup(code)?.description ?: "$code Upstream response"
        }
    /** CORE가 내보내는 X-Rosy-* 증명 헤더(카메라 출처·시퀀스·변형)를 그대로 전달한다.
     *  web_common evidence.js가 프레임 반입 검증에 쓴다 — 이 전달이 없으면 번들 화면의
     *  카메라가 항상 "확인할 수 없음"으로 실패한다(2026-10-05 태블릿 실기 확인). */
    private fun forwardRosyHeaders(response: okhttp3.Response, to: Response) {
        for (name in response.headers.names()) {
            if (!name.startsWith("x-rosy-", ignoreCase = true)) continue
            for (value in response.headers.values(name)) to.addHeader(name, value)
        }
    }
    private fun reply(code: Int, mime: String, bytes: ByteArray): Response = secure(newFixedLengthResponse(
        status(code), mime, bytes.inputStream(), bytes.size.toLong()))
    private fun secure(response: Response): Response = response.apply {
        addHeader("Cache-Control", "no-store")
        addHeader("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        addHeader("X-Content-Type-Options", "nosniff")
        addHeader("Referrer-Policy", "no-referrer")
    }
    override fun openWebSocket(session: IHTTPSession): WebSocket = Relay(session).also { sockets.add(it) }
    fun verifyIdentity() {
        check(connection.authorized()) { "session expired" }
        client.newCall(Request.Builder().url("$scheme://${target.host}:${target.port}/api/v1/system/info")
            .header("Authorization", "Bearer ${target.credential}").build()).execute().use { response ->
            check(response.isSuccessful) { "identity unavailable" }
            val bytes = response.body?.byteStream()?.let { MainActivity.readLimited(it, 65536) } ?: error("identity unavailable")
            check(JSONObject(bytes.toString(Charsets.UTF_8)).optString("robot_id") == target.id) { "robot identity mismatch" }
            identityVerified = true
        }
    }
    fun disconnect() { sockets.toList().forEach { it.disconnect() }; sockets.clear(); client.dispatcher.cancelAll(); client.connectionPool.evictAll() }
    /** Best-effort zero before cancel: bounded and off-main; CORE deadman covers an unreachable robot. */
    override fun stop() {
        if (identityVerified) runCatching {
            client.newBuilder().callTimeout(400, TimeUnit.MILLISECONDS).retryOnConnectionFailure(false).build()
                .newCall(Request.Builder().url("$scheme://${target.host}:${target.port}/api/v1/teleop")
                    .header("Authorization", "Bearer ${target.credential}")
                    .post("{\"linear\":0,\"angular\":0}".toRequestBody("application/json".toMediaTypeOrNull())).build())
                .execute().close()
        }
        identityVerified = false; disconnect(); super.stop(); client.dispatcher.executorService.shutdown()
    }

    private inner class Relay(session: IHTTPSession) : WebSocket(session) {
        private var upstream: okhttp3.WebSocket? = null
        private var ready = false
        private val pending = ArrayDeque<String>()
        private var pendingBytes = 0
        override fun onOpen() {
            if (sockets.size > 4 || !handshakeRequest.uri.startsWith("/ws/")) { disconnect(); return }
            val url = "${if (connection.secure) "wss" else "ws"}://${target.host}:${target.port}${handshakeRequest.uri}"
            upstream = client.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
                override fun onOpen(socket: okhttp3.WebSocket, response: okhttp3.Response) { synchronized(this@Relay) {
                    if (!connection.authorized()) { disconnect(); return }
                    ready = true
                    pending.forEach { socket.send(it) }; pending.clear(); pendingBytes = 0
                } }
                override fun onMessage(socket: okhttp3.WebSocket, text: String) {
                    if (text.toByteArray().size > 1048576) { disconnect(); return }
                    runCatching { send(text) }.onFailure { disconnect() }
                }
                override fun onMessage(socket: okhttp3.WebSocket, bytes: ByteString) {
                    if (bytes.size > 1048576) { disconnect(); return }
                    runCatching { send(bytes.toByteArray()) }.onFailure { disconnect() }
                }
                override fun onFailure(socket: okhttp3.WebSocket, error: Throwable, response: okhttp3.Response?) {
                    failureReported = true
                    failure(LINK_LOST); disconnect()
                }
                override fun onClosed(socket: okhttp3.WebSocket, code: Int, reason: String) { disconnect() }
            })
        }
        @Synchronized override fun onMessage(frame: WebSocketFrame) {
            if (!connection.authorized() || frame.binaryPayload.size > 65536 || frame.opCode != WebSocketFrame.OpCode.Text) { disconnect(); return }
            val text = frame.textPayload
            if (ready) {
                if (upstream?.queueSize() ?: Long.MAX_VALUE > 65536 || upstream?.send(text) != true) disconnect()
            } else {
                pendingBytes += text.toByteArray().size
                if (pending.size >= 8 || pendingBytes > 65536) { disconnect(); return }
                pending.add(text)
            }
        }
        override fun onClose(code: WebSocketFrame.CloseCode, reason: String, remote: Boolean) { upstream?.cancel(); sockets.remove(this) }
        override fun onPong(frame: WebSocketFrame) = Unit
        override fun onException(error: IOException) { upstream?.cancel(); sockets.remove(this) }
        fun disconnect() { upstream?.cancel(); runCatching { close(WebSocketFrame.CloseCode.GoingAway, "connection ended", false) }; sockets.remove(this) }
    }
}

/** Shown on the session bar while the robot does not answer; the next good reply restores "연결됨". */
const val LINK_LOST = "로봇이 응답하지 않습니다. 다시 닿으면 자동으로 이어집니다. 계속되면 '로봇 목록'에서 다시 선택하세요."
