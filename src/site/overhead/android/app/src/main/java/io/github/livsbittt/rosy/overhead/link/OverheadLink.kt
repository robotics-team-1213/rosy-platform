package io.github.livsbittt.rosy.overhead.link

import android.util.Log
import io.github.livsbittt.rosy.overhead.settings.PairingUri
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString

enum class LinkState { DISCONNECTED, CONNECTING, STREAMING }

/** Why the link is not streaming. The UI maps these to Korean text. */
sealed interface LinkError {
    /** Upgrade refused with 401 or close 4401: token is unknown or not allowed for this source. */
    data object Unauthorized : LinkError

    /** Close 4400: the adapter speaks another protocol version. Retrying cannot help. */
    data object ProtocolMismatch : LinkError

    /** Close 4409: another connection with the same source replaced this one. */
    data object Replaced : LinkError

    data class InvalidConfig(val field: String) : LinkError
    data class Network(val detail: String) : LinkError
    data class Closed(val code: Int, val reason: String) : LinkError
}

data class LinkStatus(
    val state: LinkState = LinkState.DISCONNECTED,
    val error: LinkError? = null,
    /** True after 4400/4409: the link gave up and waits for the operator. */
    val stopped: Boolean = false,
    val sentFps: Double = 0.0,
    val kbps: Double = 0.0,
    val sent: Long = 0,
    val dropped: Long = 0,
    val config: OverheadConfig = OverheadConfig.DEFAULT,
)

/** Sensor facts reported in `hello`. Updated by the camera once it knows the real resolution. */
data class SensorInfo(val width: Int, val height: Int, val rotationDeg: Int)

/**
 * OkHttp WebSocket to the observation adapter (design section 3).
 *
 * - `Authorization: Bearer <token>` on the upgrade, `hello` right after open.
 * - `config` from the adapter is applied and published through [status].
 * - Frames go out only while STREAMING and only when nothing is queued (latest-only);
 *   nothing is buffered while disconnected.
 *
 * Limits of latest-only and age_ms (measured on device in A3; no socket tuning until then):
 * - The gate is OkHttp's `WebSocket.queueSize()`, i.e. bytes not yet written to the socket.
 *   Once a frame is written it leaves that queue but can still sit in the kernel TCP send
 *   buffer (and Wi-Fi driver queues), so on a slow link one or more earlier frames may still
 *   be in flight when the next one is admitted. Latest-only therefore bounds the app-side
 *   queue to one frame, not the end-to-end queue.
 * - `age_ms` is measured when the frame is enqueued with `WebSocket.send`. It covers capture,
 *   analysis and encoding but not time spent in the OkHttp writer, kernel send buffer or
 *   network. The adapter's `captured_at = received - age_ms` is therefore later than the true
 *   capture time by that transmit delay.
 * - Reconnects with [Backoff]; close 4400 or 4409 stops retrying.
 */
class OverheadLink(
    private val pairing: PairingUri,
    private val appVersion: String,
    private val device: String,
    private val client: OkHttpClient = defaultClient(),
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val lock = Any()
    private val backoff = Backoff()
    private val policy = LatestOnlyPolicy()
    private val meter = RateMeter()

    private val _status = MutableStateFlow(LinkStatus())
    val status: StateFlow<LinkStatus> = _status.asStateFlow()

    @Volatile
    var sensor: SensorInfo = OverheadConfig.DEFAULT.let { SensorInfo(it.width, it.height, 0) }

    // Guarded by lock.
    private var socket: WebSocket? = null
    private var generation = 0
    private var running = false
    private var started = false
    private var reconnectJob: Job? = null
    private var seq = 0L
    private var sentCount = 0L

    /** Starts connecting. One-shot: after [stop] create a new link. */
    fun start() {
        synchronized(lock) {
            check(!started) { "OverheadLink is single-use" }
            started = true
            running = true
            backoff.reset()
            policy.resetCount()
            meter.clear()
            sentCount = 0
        }
        _status.value = LinkStatus()
        scope.launch {
            while (isActive) {
                refreshCounters()
                delay(1_000)
            }
        }
        connect()
    }

    fun stop() {
        val ws: WebSocket?
        synchronized(lock) {
            running = false
            generation++
            reconnectJob?.cancel()
            reconnectJob = null
            ws = socket
            socket = null
        }
        ws?.close(1000, "stopped")
        scope.cancel()
        _status.update { it.copy(state = LinkState.DISCONNECTED, sentFps = 0.0, kbps = 0.0) }
    }

    /**
     * Latest-only gate, checked before encoding so a frame that cannot be sent costs no CPU.
     * Returns false without counting while not streaming (nothing is buffered then), and false
     * with a counted drop while the previous frame is still queued on the socket.
     */
    fun admitFrame(): Boolean {
        val ws = synchronized(lock) { socket } ?: return false
        if (_status.value.state != LinkState.STREAMING) return false
        return policy.admit(ws.queueSize())
    }

    /** Counts a frame dropped before sending (for example a JPEG above `max_bytes`). */
    fun countDrop() {
        policy.countDrop()
    }

    /**
     * Sends header + JPEG as one binary message. [captureNanos] is on the System.nanoTime clock;
     * age_ms is measured at enqueue time, so encoding is included but socket and network
     * transmit time are not (see the class comment).
     */
    fun sendFrame(jpeg: ByteArray, length: Int, width: Int, height: Int, rotationDeg: Int, captureNanos: Long): Boolean {
        val maxBytes = _status.value.config.maxBytes
        if (length > maxBytes) {
            policy.countDrop()
            return false
        }
        val frame = ByteArray(FrameHeader.SIZE + length)
        System.arraycopy(jpeg, 0, frame, FrameHeader.SIZE, length)
        synchronized(lock) {
            val ws = socket ?: return false
            val now = System.nanoTime()
            val ageMs = FrameHeader.clampU32((now - captureNanos) / 1_000_000)
            FrameHeader(seq, ageMs, width, height, rotationDeg).writeInto(frame)
            if (!ws.send(frame.toByteString())) return false
            seq = FrameHeader.nextSeq(seq)
            sentCount++
            meter.record(now, frame.size)
        }
        return true
    }

    private fun connect() {
        val gen: Int
        synchronized(lock) {
            if (!running) return
            gen = ++generation
            seq = 0
        }
        _status.update { it.copy(state = LinkState.CONNECTING) }
        val request = Request.Builder()
            .url(pairing.wsUrl)
            .header("Authorization", "Bearer ${pairing.token}")
            .build()
        val ws = client.newWebSocket(request, Listener(gen))
        synchronized(lock) {
            if (gen == generation && running) socket = ws else ws.cancel()
        }
    }

    private fun isCurrent(gen: Int): Boolean = synchronized(lock) { running && gen == generation }

    /** Drops the socket of [gen] and either retries with backoff or stops for good. */
    private fun onLost(gen: Int, error: LinkError, fatal: Boolean) {
        synchronized(lock) {
            if (!running || gen != generation) return
            socket = null
            generation++
            if (fatal) {
                running = false
            } else {
                val delayMs = backoff.nextDelayMs()
                reconnectJob = scope.launch {
                    delay(delayMs)
                    connect()
                }
            }
        }
        Log.w(TAG, "link lost: $error fatal=$fatal")
        _status.update { it.copy(state = LinkState.DISCONNECTED, error = error, stopped = fatal) }
    }

    private fun refreshCounters() {
        val now = System.nanoTime()
        val sent = synchronized(lock) { sentCount }
        _status.update {
            it.copy(sentFps = meter.fps(now), kbps = meter.kbps(now), sent = sent, dropped = policy.dropped)
        }
    }

    private inner class Listener(private val gen: Int) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (!isCurrent(gen)) {
                webSocket.close(1000, "stale")
                return
            }
            val s = sensor
            webSocket.send(Protocol.hello(pairing.source, appVersion, device, s.width, s.height, s.rotationDeg))
            backoff.reset()
            Log.i(TAG, "connected to ${pairing.wsUrl}")
            _status.update { it.copy(state = LinkState.STREAMING, error = null, stopped = false) }
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (!isCurrent(gen)) return
            when (val msg = Protocol.parseServerMessage(text)) {
                is ServerMessage.Config -> {
                    Log.i(TAG, "config ${msg.config}")
                    _status.update { it.copy(config = msg.config) }
                }
                is ServerMessage.Status -> Log.d(TAG, "status $msg")
                is ServerMessage.Invalid -> {
                    Log.w(TAG, "invalid server message (${msg.reason}): $text")
                    _status.update { it.copy(error = LinkError.InvalidConfig(msg.reason)) }
                }
                is ServerMessage.Unknown -> Log.d(TAG, "ignored message type ${msg.type}")
            }
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            Log.d(TAG, "ignored binary message of ${bytes.size} bytes")
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
            handleClose(code, reason)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            handleClose(code, reason)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val error = if (response?.code == 401) {
                LinkError.Unauthorized
            } else {
                LinkError.Network(t.message ?: t.javaClass.simpleName)
            }
            onLost(gen, error, fatal = false)
        }

        private fun handleClose(code: Int, reason: String) {
            when (code) {
                Protocol.CLOSE_BAD_PROTO -> onLost(gen, LinkError.ProtocolMismatch, fatal = true)
                Protocol.CLOSE_UNAUTHORIZED -> onLost(gen, LinkError.Unauthorized, fatal = true)
                Protocol.CLOSE_REPLACED -> onLost(gen, LinkError.Replaced, fatal = true)
                else -> onLost(gen, LinkError.Closed(code, reason), fatal = false)
            }
        }
    }

    companion object {
        private const val TAG = "OverheadLink"

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(10, TimeUnit.SECONDS)
            .build()
    }
}
