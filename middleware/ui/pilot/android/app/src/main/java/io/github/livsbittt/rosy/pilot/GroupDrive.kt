package io.github.livsbittt.rosy.pilot

import android.content.Context
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.view.MotionEvent
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.min

/** One held input, two independently authenticated CORE requests. No leader/follower offset is inferred. */
class GroupDrive(private val context: Context, private val first: PilotConnection, private val second: PilotConnection,
    private val onState: (String) -> Unit) {
    private val main = android.os.Handler(android.os.Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val requests = Executors.newFixedThreadPool(2)
    private val cameraPool = Executors.newFixedThreadPool(2)
    private val loop = Executors.newSingleThreadExecutor()
    private val running = AtomicBoolean(true)
    private val a = Endpoint(first)
    private val b = Endpoint(second)
    private val fanout = GroupCommandFanout(requests,
        { body -> a.request("/api/v1/teleop", body).first },
        { body -> b.request("/api/v1/teleop", body).first })
    @Volatile private var armed = false
    @Volatile private var stopRequested = false
    @Volatile private var held = false
    @Volatile private var x = 0f
    @Volatile private var y = 0f
    private var maxLinear = 0.0
    private var maxAngular = 0.0
    private var modeHeldA = false
    private var modeHeldB = false
    private var stick: Stick? = null
    private var armButton: android.widget.Button? = null

    private inner class Endpoint(val connection: PilotConnection) {
        @Volatile var lastFrameAt = 0L
        private val target = connection.target
        private val client = connection.client().newBuilder().callTimeout(450, TimeUnit.MILLISECONDS)
            .retryOnConnectionFailure(false).build()
        private val base = "${if (connection.secure) "https" else "http"}://${target.host}:${target.port}"
        fun request(path: String, json: String? = null): Pair<Int, ByteArray> {
            check(connection.authorized()) { "approval expired" }
            val builder = Request.Builder().url(base + path).header("Authorization", "Bearer ${target.credential}")
            if (json != null) builder.post(json.toRequestBody("application/json".toMediaType()))
            client.newCall(builder.build()).execute().use { response ->
                val bytes = response.body?.byteStream()?.let { MainActivity.readLimited(it, if (path.endsWith("/frame")) 2_000_000 else 65_536) } ?: ByteArray(0)
                return response.code to bytes
            }
        }
        fun rawFrame(sequence: Long): ByteArray? {
            check(connection.authorized()) { "approval expired" }
            val request = Request.Builder().url("$base/api/v1/vision/front/frame?sequence=$sequence&overlay=false")
                .header("Authorization", "Bearer ${target.credential}").build()
            client.newCall(request).execute().use { response ->
                if (response.code != 200) return null
                check(response.header("Content-Type")?.startsWith("image/jpeg") == true &&
                    response.header("X-Rosy-Camera-Variant") == "raw" &&
                    response.header("X-Rosy-Camera-Sequence") == sequence.toString() &&
                    response.header("X-Rosy-Camera-Captured-At")?.toDoubleOrNull()?.isFinite() == true &&
                    !response.header("X-Rosy-Camera-Frame-Id").isNullOrBlank()) { "camera provenance unavailable" }
                return response.body?.byteStream()?.let { MainActivity.readLimited(it, 2_000_000) }
            }
        }
        fun close() { client.dispatcher.cancelAll(); client.connectionPool.evictAll(); client.dispatcher.executorService.shutdown() }
    }

    private fun limits(endpoint: Endpoint): Pair<Double, Double> {
        val (code, bytes) = endpoint.request("/api/v1/system/capabilities")
        check(code == 200) { "capabilities $code" }
        val caps = JSONObject(bytes.toString(Charsets.UTF_8))
        check(caps.optBoolean("teleop")) { "teleop withheld" }
        val items = caps.optJSONObject("controls")?.optJSONArray("items") ?: error("drive capability missing")
        val base = (0 until items.length()).mapNotNull { items.optJSONObject(it) }.firstOrNull { it.optString("kind") == "base_velocity" }
            ?: error("drive capability missing")
        val linear = base.optDouble("max_linear", 0.0)
        val angular = base.optDouble("max_angular", 0.0)
        check(linear.isFinite() && angular.isFinite() && linear > 0 && angular > 0) { "drive limit unavailable" }
        val (safetyCode, safetyBytes) = endpoint.request("/api/v1/safety/state")
        check(safetyCode == 200) { "safety state $safetyCode" }
        val safety = JSONObject(safetyBytes.toString(Charsets.UTF_8))
        val live = safety.optJSONObject("limits") ?: error("safety limit unavailable")
        return min(linear, live.optDouble("manual_linear", 0.0)) to min(angular, live.optDouble("manual_angular", 0.0))
    }

    fun view(): View {
        val ui = PilotViews(context)
        val dp = ui::dp
        val root = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(16), dp(12), dp(16), dp(12))
            setBackgroundColor(PilotColors.background)
        }
        root.addView(ui.label("2대 함께 조종", 24f))
        root.addView(ui.label("같은 속도·회전 명령을 두 로봇에 보냅니다. 위치를 유지하는 추종 모드는 준비 중입니다.", 14f, true))
        val cameras = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }
        root.addView(cameras, LinearLayout.LayoutParams(-1, 0, 1f))
        for ((endpoint, title) in listOf(a to first.target.id, b to second.target.id)) {
            val column = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(4), dp(4), dp(4), dp(4)) }
            column.addView(ui.label(title, 17f))
            val frame = ImageView(context).apply { scaleType = ImageView.ScaleType.FIT_CENTER; setBackgroundColor(PilotColors.disabled) }
            column.addView(frame, LinearLayout.LayoutParams(-1, 0, 1f))
            val cameraState = ui.label("카메라 대기", 13f, true)
            column.addView(cameraState)
            cameras.addView(column, LinearLayout.LayoutParams(0, -1, 1f))
            cameraPool.execute { cameraLoop(endpoint, frame, cameraState) }
        }
        val controls = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL }
        root.addView(controls)
        val state = ui.label("조종 준비 전 · 두 로봇 정지", 15f)
        controls.addView(state, LinearLayout.LayoutParams(0, -2, 1f))
        armButton = ui.button("두 로봇 수동 조종 시작", true) { arm() }.also { controls.addView(it) }
        controls.addView(ui.button("두 로봇 정지") { disarm("두 로봇 정지 요청") })
        stick = Stick(context) { sx, sy, active -> x = sx; y = sy; held = active }.also {
            root.addView(it, LinearLayout.LayoutParams(-1, dp(170)))
        }
        onState("두 로봇 연결 · 조종 준비 전")
        loop.execute { driveLoop() }
        return root
    }

    private fun cameraLoop(endpoint: Endpoint, frame: ImageView, state: TextView) {
        var lastSequence = -1L
        while (running.get()) {
            try {
                val (code, bytes) = endpoint.request("/api/v1/vision/front/status")
                val status = if (code == 200) JSONObject(bytes.toString(Charsets.UTF_8)) else null
                val sequence = status?.optLong("sequence", -1) ?: -1
                if (status?.optBoolean("available") == true && status.optBoolean("raw_available") &&
                    status.optLong("raw_sequence", -2) == sequence && sequence >= 0 && sequence != lastSequence) {
                    val jpeg = endpoint.rawFrame(sequence) ?: error("frame unavailable")
                    val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: error("bad frame")
                    lastSequence = sequence
                    endpoint.lastFrameAt = android.os.SystemClock.elapsedRealtime()
                    main.post { if (running.get()) { frame.setImageBitmap(bitmap); state.text = "카메라 연결됨" } }
                } else if (status?.optBoolean("available") != true)
                    main.post { if (running.get()) state.text = "카메라 프레임 수신 대기" }
            } catch (_: Exception) { main.post { if (running.get()) state.text = "카메라 연결 확인 중" } }
            try { Thread.sleep(650) } catch (_: InterruptedException) { break }
        }
    }

    private fun arm() {
        stopRequested = false; held = false; stick?.release()
        armButton?.isEnabled = false
        worker.execute {
            try {
                check(running.get() && !stopRequested) { "session closed" }
                val l1 = limits(a); val l2 = limits(b)
                check(camerasFresh()) { "camera unavailable" }
                maxLinear = min(l1.first, l2.first); maxAngular = min(l1.second, l2.second)
                check(maxLinear > 0 && maxAngular > 0) { "drive limit zero" }
                check(a.request("/api/v1/mode", "{\"mode\":\"MANUAL\"}").first == 200) { "first manual mode refused" }
                modeHeldA = true
                check(b.request("/api/v1/mode", "{\"mode\":\"MANUAL\"}").first == 200) { "second manual mode refused" }
                modeHeldB = true
                check(running.get() && !stopRequested) { "session closed" }
                armed = true
                main.post { onState("공용 조이스틱 준비 · 누르는 동안만 주행"); armButton?.text = "조종 중" }
            } catch (_: Exception) {
                disarmOnWorker("두 로봇 조종 시작 실패 · 연결·권한·안전 상태 확인")
            }
            main.post { if (!armed) armButton?.isEnabled = true }
        }
    }

    private fun driveLoop() {
        var previousLinear = 0.0
        var previousAngular = 0.0
        while (running.get()) {
            if (armed) {
                if (!camerasFresh()) {
                    held = false; armed = false
                    worker.execute { disarmOnWorker("카메라 영상이 끊겼습니다 · 두 로봇 정지 요청") }
                    continue
                }
                val wantedLinear = if (held) (-y * maxLinear).coerceIn(-maxLinear, maxLinear) else 0.0
                val wantedAngular = if (held) (-x * maxAngular).coerceIn(-maxAngular, maxAngular) else 0.0
                // Match the Pilot's ramp-up/instant-release behavior; no motion accumulates across disarm.
                val linear = if (!held || kotlin.math.abs(wantedLinear) < kotlin.math.abs(previousLinear)) wantedLinear
                    else wantedLinear.coerceIn(previousLinear - maxLinear * 0.2, previousLinear + maxLinear * 0.2)
                val angular = if (!held || kotlin.math.abs(wantedAngular) < kotlin.math.abs(previousAngular)) wantedAngular
                    else wantedAngular.coerceIn(previousAngular - maxAngular * 0.2, previousAngular + maxAngular * 0.2)
                previousLinear = linear; previousAngular = angular
                try {
                    check(fanout.send(linear, angular)) { "teleop refused" }
                } catch (_: Exception) {
                    held = false; armed = false
                    worker.execute { disarmOnWorker("한쪽 연결·명령 실패 · 두 로봇 정지 요청") }
                }
            } else { previousLinear = 0.0; previousAngular = 0.0 }
            try { Thread.sleep(100) } catch (_: InterruptedException) { break }
        }
    }

    fun disarm(message: String) { stopRequested = true; held = false; armed = false; worker.execute { disarmOnWorker(message) } }

    private fun camerasFresh(): Boolean {
        val now = android.os.SystemClock.elapsedRealtime()
        return a.lastFrameAt != 0L && b.lastFrameAt != 0L && now - a.lastFrameAt < 2000 && now - b.lastFrameAt < 2000
    }

    private fun disarmOnWorker(message: String) {
        held = false; armed = false
        val zero = "{\"linear\":0,\"angular\":0}"
        // Stop both even if one endpoint is unreachable. CORE deadman is the final fallback.
        val one = if (modeHeldA) requests.submit { runCatching { a.request("/api/v1/teleop", zero) } } else null
        val two = if (modeHeldB) requests.submit { runCatching { b.request("/api/v1/teleop", zero) } } else null
        runCatching { one?.get(600, TimeUnit.MILLISECONDS) }; runCatching { two?.get(600, TimeUnit.MILLISECONDS) }
        if (modeHeldA) runCatching { a.request("/api/v1/mode", "{\"mode\":\"IDLE\"}") }
        if (modeHeldB) runCatching { b.request("/api/v1/mode", "{\"mode\":\"IDLE\"}") }
        modeHeldA = false; modeHeldB = false
        main.post { onState(message); armButton?.apply { text = "두 로봇 수동 조종 시작"; isEnabled = true }; stick?.release() }
    }

    fun close() {
        running.set(false); stopRequested = true; held = false; armed = false
        // The owning activity's PilotProxy.stop() also sends zero to both robots.
        cameraPool.shutdownNow(); loop.shutdownNow()
        worker.execute { disarmOnWorker("두 로봇 정지 요청"); a.close(); b.close(); requests.shutdownNow() }
        worker.shutdown()
    }

    private class Stick(context: Context, private val changed: (Float, Float, Boolean) -> Unit) : View(context) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private var x = 0f; private var y = 0f; private var held = false
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val cx = width / 2f; val cy = height / 2f; val radius = min(width, height) * 0.37f
            paint.color = PilotColors.disabled; canvas.drawCircle(cx, cy, radius, paint)
            paint.color = PilotColors.foreground; paint.style = Paint.Style.STROKE; paint.strokeWidth = 3f
            canvas.drawCircle(cx, cy, radius, paint); paint.style = Paint.Style.FILL
            paint.color = PilotColors.rose; canvas.drawCircle(cx + x * radius, cy + y * radius, radius * 0.28f, paint)
        }
        override fun onTouchEvent(event: MotionEvent): Boolean {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                    val radius = min(width, height) * 0.37f
                    x = ((event.x - width / 2f) / radius).coerceIn(-1f, 1f)
                    y = ((event.y - height / 2f) / radius).coerceIn(-1f, 1f)
                    held = true; changed(x, y, true); invalidate(); return true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> { release(); return true }
            }
            return true
        }
        fun release() { x = 0f; y = 0f; held = false; changed(0f, 0f, false); invalidate() }
    }
}
