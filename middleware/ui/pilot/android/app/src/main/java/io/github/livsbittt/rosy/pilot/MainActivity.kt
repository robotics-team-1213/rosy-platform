package io.github.livsbittt.rosy.pilot

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.concurrent.Executors
import io.github.livsbittt.rosy.cam.health.DeviceHealth
import io.github.livsbittt.rosy.cam.health.ScreenCoolingPolicy
import io.github.livsbittt.rosy.cam.health.ScreenPower

/** Discover, select, join. A code appears only when the selected server requires pairing. */
class MainActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private val vault by lazy { PairingVault(this) }
    private val peerVault by lazy { PeerRelationshipVault(this) }
    private val peerUi by lazy { PeerApprovalUi(this, { AndroidPeerIdentity(this) }, peerVault) }
    private var candidates = CandidateStore()
    private var discovery: RobotDiscovery? = null
    private var proxy: PilotProxy? = null
    /** 세션 상단 배너의 정상 문구 — 일시 실패 뒤 회복 콜백이 이 값으로 되돌린다. */
    @Volatile private var connectedLabel: String? = null
    private var web: WebView? = null
    private var pairingDialog: AlertDialog? = null
    @Volatile private var session: LobbySession? = null
    @Volatile private var attempt = 0L
    private var foreground = false
    private var opening = false
    private var lastError: String? = null
    private var lastSelectedCandidate: Candidate? = null
    private var reselect: Candidate? = null
    private val screenSleep = PendingScreenSleep()
    private val sleeping get() = screenSleep.active
    private var pendingApprovedSleep = false
    private val cooling = ScreenCoolingPolicy()
    private val screenPower by lazy { ScreenPower(this) }
    private val health by lazy { TabletHealth(this) { value -> showHealth(value) } }
    private var lastHealth: DeviceHealth? = null
    private lateinit var healthText: TextView
    private lateinit var root: LinearLayout
    private lateinit var status: TextView
    private lateinit var robots: LinearLayout
    private var shownCandidates: List<Candidate>? = null
    private var shownCooling = false
    private val refreshTick = object : Runnable {
        override fun run() { if (!foreground) return; refresh(); if (foreground) main.postDelayed(this, 5000) }
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state); window.addFlags(WindowManager.LayoutParams.FLAG_SECURE); showLobby()
        if (android.os.Build.VERSION.SDK_INT >= 33) onBackInvokedDispatcher.registerOnBackInvokedCallback(
            android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT) { backToLobbyOrExit() }
    }
    private val views by lazy { PilotViews(this) }
    private fun label(text: String, size: Float = 16f) = views.label(text, size)
    private fun button(text: String, action: () -> Unit) = views.button(text, action = action)
    private fun showLobby() {
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(PilotColors.background) }
        setContentView(root)
        shownCandidates = null
        window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val compact = resources.configuration.screenWidthDp < 720
        val columns = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        root.addView(columns, LinearLayout.LayoutParams(-1, -1))
        healthText = views.label("태블릿 상태 확인 중", 14f, true)
        lastHealth?.let { renderHealth(it) }
        val deviceButton = button("기기·연결") { deviceDetails() }
        if (!compact) {
            val identity = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(views.dp(32), views.dp(40), views.dp(32), views.dp(24)) }
            columns.addView(identity, LinearLayout.LayoutParams(views.dp(260), -1))
            identity.addView(label("ROSY", 22f).apply { setTextColor(PilotColors.rose) })
            identity.addView(label("Pilot", 32f).apply { setTypeface(typeface, android.graphics.Typeface.BOLD) })
            identity.addView(views.label("로봇을 선택하고\n직접 조종하세요.", 16f, true).apply { setPadding(0, views.dp(24), 0, 0) })
            identity.addView(View(this), LinearLayout.LayoutParams(1, 0, 1f))
            identity.addView(healthText)
            identity.addView(deviceButton, LinearLayout.LayoutParams(-2, -2).apply { gravity = android.view.Gravity.START; topMargin = views.dp(8) })
        }
        val list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(
                views.dp(if (compact) 16 else 24), views.dp(if (compact) 16 else 40),
                views.dp(if (compact) 16 else 40), views.dp(if (compact) 16 else 24),
            )
        }
        columns.addView(list, if (compact) LinearLayout.LayoutParams(-1, -1) else LinearLayout.LayoutParams(0, -1, 1f))
        val header = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL }
        header.addView(label("로봇 선택", 28f).apply { typeface = android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL) }, LinearLayout.LayoutParams(0, -2, 1f))
        header.addView(views.button("다시 찾기", primary = true) { lastError = null; endSession { opening = false; status.text = "같은 Wi-Fi에서 로봇을 다시 찾고 있습니다…"; startDiscovery() }; opening = true })
        list.addView(header)
        status = views.label("같은 Wi-Fi에서 켜진 로봇을 찾고 있습니다…", 16f, true).apply { setPadding(0, views.dp(16), 0, views.dp(28)) }; list.addView(status)
        robots = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        list.addView(ScrollView(this).apply { addView(robots) }, LinearLayout.LayoutParams(-1, 0, 1f))
        if (compact) {
            list.addView(healthText)
            list.addView(deviceButton, LinearLayout.LayoutParams(-1, -2))
        }
    }
    private fun startDiscovery() {
        if (!foreground || opening || sleeping || cooling.coolingRequired || discovery != null) return
        discovery = RobotDiscovery(this, candidates) { main.post { refresh() } }
        runCatching { discovery!!.start() }.onFailure { status.text = "Wi-Fi 연결을 확인한 뒤 다시 찾아주세요." }
        main.removeCallbacks(refreshTick); main.postDelayed(refreshTick, 5000)
    }
    private fun refresh() {
        val current = session
        if (current != null && !current.authorized()) {
            lastError = "연결 끊김 · 로그인 세션이 끝났거나 로봇 목록이 바뀌었습니다. 로봇을 다시 선택하면 승인 기록으로 다시 연결합니다."
            returnToLobby(); status.text = lastError; return
        }
        if (web != null || opening) return
        val records = candidates.records()
        reselect?.let { wanted -> records.firstOrNull { it.host == wanted.host && it.port == wanted.port }?.let { reselect = null; select(it); return } }
        status.text = lastError ?: if (cooling.coolingRequired) "태블릿 발열이 내려갈 때까지 조종 연결을 닫았습니다." else if (records.isEmpty()) discovery?.status ?: "같은 Wi-Fi에서 로봇을 찾고 있습니다…" else "${records.size}대 발견 · 연결할 로봇을 선택하세요."
        if (shownCandidates == records && shownCooling == cooling.coolingRequired) return
        shownCandidates = records; shownCooling = cooling.coolingRequired; robots.removeAllViews()
        if (records.isEmpty()) { robots.addView(label(if (cooling.coolingRequired) "태블릿이 식으면 다시 연결할 수 있습니다." else "로봇이 없나요? Wi-Fi와 전원을 확인하세요.", 16f)); return }
        records.forEach { candidate ->
            val valid = runCatching { candidates.addresses(candidate.host, candidate.port) != null }.getOrDefault(false)
            robots.addView(views.robot(candidate, valid && !cooling.coolingRequired) { select(candidate) },
                LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = views.dp(12) })
        }
    }
    private fun select(incoming: Candidate) {
        if (opening || sleeping || cooling.coolingRequired || web != null) return
        lastError = null; reselect = null
        val addresses =runCatching { candidates.addresses(incoming.host, incoming.port) }.getOrNull() ?: return
        val candidate = incoming.copy(addresses = addresses)
        lastSelectedCandidate = candidate
        opening = true
        val version = ++attempt; val store = candidates
        for (i in 0 until robots.childCount) robots.getChildAt(i).isEnabled = false
        // The loading state changes the rendered cards; failure/cancel must rebuild them.
        shownCandidates = null
        status.text = "${candidate.name} · 연결 확인 중…"
        io.execute {
            if (attempt != version) return@execute
            try {
                val direct = if (candidate.secure) peerUi.connect(candidate, store,
                    { version == attempt && foreground }, { if (version == attempt) returnToLobby() }) else null
                if (version != attempt) return@execute
                val offer = direct?.let { LobbyOffer("paired", it.target.id) } ?: LobbyPairing.offer(candidate)
                val remembered = if (direct != null) SavedLogin(SavedLoginStatus.READY, direct)
                    else if (offer.mode == "paired") vault.inspect(candidate, offer, store) else SavedLogin(SavedLoginStatus.NONE)
                val saved = remembered.session
                val reused = direct ?: saved?.takeIf { LobbyPairing.reuse(it) }
                main.post {
                    if (version != attempt || !foreground) return@post
                    if (reused != null) join(candidate, offer, store, version, null, reused)
                    else if (offer.mode == "development") join(candidate, offer, store, version, null)
                    else pairingCode(candidate, offer, store, version, remembered.status)
                }
            } catch (error: Exception) {
                if (LinkStatus.reason(error) in setOf(LinkReason.APPROVAL_EXPIRED, LinkReason.APPROVAL_REVOKED))
                    main.post { if (version == attempt && foreground) reapprove(candidate, LinkStatus.reason(error)) }
                failed(version, candidate, LinkStatus.failure(error, candidate.secure))
            }
        }
    }
    private fun pairingCode(candidate: Candidate, offer: LobbyOffer, store: CandidateStore, version: Long, savedStatus: SavedLoginStatus) {
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val input = EditText(this).apply {
            hint = "8자리 로그인 코드"; textSize = 28f; setSingleLine(); setTextColor(PilotColors.foreground)
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD or android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            filters = arrayOf(android.text.InputFilter.LengthFilter(9))
        }
        fun canceled() { if (version == attempt) { opening = false; refresh() } }
        val dialog = AlertDialog.Builder(this).setTitle("로봇 로그인 코드")
            .setMessage((if (savedStatus == SavedLoginStatus.EXPIRED) "저장된 연결 기록은 유지되어 있지만 로그인이 만료되었습니다. 새 코드가 필요합니다.\n\n" else "") + "${candidate.name}에 표시된 숫자·영문 코드를 입력하세요.").setView(input)
            .setPositiveButton("연결", null).setNegativeButton("취소") { _, _ -> canceled() }
            .setOnCancelListener { canceled() }.create()
        pairingDialog = dialog
        dialog.setOnDismissListener { if (pairingDialog === dialog) pairingDialog = null; if (web == null) window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) }
        dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val code = runCatching { PairingCode.normalize(input.text.toString()) }.getOrNull()
            if (code == null) { input.error = "숫자·영문 8자리 (XXXX-XXXX)"; return@setOnClickListener }
            input.text.clear(); dialog.dismiss(); join(candidate, offer, store, version, code)
        } }
        dialog.show()
    }
    private fun join(candidate: Candidate, offer: LobbyOffer, store: CandidateStore, version: Long, code: String?, reused: LobbySession? = null) {
        status.text = "${candidate.name} · ${if (offer.mode == "development") "개발 연결" else "페어링"} 중…"
        io.execute {
            if (version != attempt) return@execute
            var relay: PilotProxy? = null
            try {
                val approved = reused ?: LobbyPairing.connect(candidate, offer, store, code)
                if (version != attempt) return@execute
                relay = PilotProxy(approved, AssetBundle(assets),
                    { message -> main.post { if (version == attempt) status.text = "${candidate.name} · 연결 끊김 · $message" } },
                    { main.post { if (version == attempt) connectedLabel?.let { status.text = it } } })
                relay.verifyIdentity(); relay.start(5000, false)
                if (offer.mode == "paired" && version == attempt) vault.saveVerified(candidate, approved)
                val ready = relay
                main.post {
                    if (version != attempt || !foreground || web != null) { io.execute { ready.stop() }; return@post }
                    opening = false; session = approved; proxy = ready
                    root.removeAllViews()
                    val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL; setPadding(views.dp(12), views.dp(4), views.dp(12), views.dp(4)) }
                    bar.addView(button("로봇 목록") { returnToLobby() })
                    status = label("${candidate.name} · ${approved.target.id}", 18f).apply { setPadding(views.dp(20), 0, views.dp(20), 0); typeface = android.graphics.Typeface.create("sans-serif-medium", android.graphics.Typeface.NORMAL); maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END }
                    bar.addView(status, LinearLayout.LayoutParams(0, -2, 1f))
                    bar.addView(button("기기·연결") { deviceDetails(candidate) })
                    root.addView(bar)
                    healthText = label("태블릿 상태 확인 중", 14f); lastHealth?.let { renderHealth(it) }
                    val view = WebView(this); web = view; view.setBackgroundColor(PilotColors.background)
                    view.webChromeClient = object : android.webkit.WebChromeClient() {
                        override fun onConsoleMessage(message: android.webkit.ConsoleMessage): Boolean {
                            android.util.Log.e("RosyPilot", "Web console ${message.messageLevel()} ${message.sourceId().substringBefore('?')} line ${message.lineNumber()}")
                            return true
                        }
                    }
                    // Private debug-device visual evidence is allowed after pairing; code dialogs
                    // remain protected and release sessions always block captures.
                    if (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0) window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                    else window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                    view.settings.apply {
                        javaScriptEnabled = true; domStorageEnabled = true; allowFileAccess = false; allowContentAccess = false
                        mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
                        setSupportMultipleWindows(false); javaScriptCanOpenWindowsAutomatically = false; safeBrowsingEnabled = true
                    }
                    view.webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean =
                            request.url.scheme != "http" || "http://${request.url.encodedAuthority}" != ready.origin
                    }
                    root.addView(view, LinearLayout.LayoutParams(-1, 0, 1f))
                    CookieManager.getInstance().apply {
                        setAcceptCookie(true); setAcceptThirdPartyCookies(view, false)
                        setCookie(ready.origin, "rosy-shell=${ready.capability}; Path=/; HttpOnly; SameSite=Strict") {
                            if (proxy === ready && web === view) view.loadUrl("${ready.origin}/pilot")
                        }
                    }
                    val connectionLabel = when (approved.peerApproval?.persistent) { true -> "승인 유지 · 연결됨"; false -> "기간 제한 승인 · 연결됨"; null -> if (offer.mode == "development") "개발 연결" else "연결됨" }
                    connectedLabel = "${candidate.name} · ${approved.target.id} · $connectionLabel"
                    status.text = connectedLabel
                }
            } catch (error: Exception) {
                // Exception messages and HTTP bodies can contain credentials; log class and locations only.
                android.util.Log.e("RosyPilot", "Join failed: ${error.javaClass.simpleName}\n" + error.stackTrace.take(8).joinToString("\n"))
                relay?.stop(); failed(version, candidate, when {
                    error is PairingRejected && error.status == 401 -> "로그인 코드가 유효하지 않습니다. 로봇에서 새 코드를 발급한 뒤 다시 연결하세요."
                    error is PairingRejected && error.status == 429 -> "연결 요청이 많습니다. 잠시 뒤 다시 선택하세요."
                    else -> LinkStatus.failure(error, candidate.secure)
                })
            }
        }
    }
    private fun failed(version: Long, candidate: Candidate, message: String) { main.post {
        if (version != attempt || !foreground) return@post
        opening = false
        lastError = "${candidate.name.ifBlank { "선택한 로봇" }} · $message"
        refresh(); status.text = lastError
    } }
    private fun endSession(forget: Candidate? = null, afterClosed: (() -> Unit)? = null) {
        // Resource-owning completion callbacks must run their stale-attempt cleanup.
        attempt++; peerUi.close(); screenSleep.revoke(); opening = false; main.removeCallbacks(refreshTick)
        connectedLabel = null
        val closingAttempt = attempt
        pairingDialog?.dismiss(); pairingDialog = null
        web?.evaluateJavascript("window.dispatchEvent(new Event('blur')); sessionStorage.clear();", null)
        web?.stopLoading(); web?.destroy(); web = null
        val oldRelay = proxy; proxy = null; session = null
        val oldCandidates = candidates; candidates = CandidateStore()
        discovery?.stop(clearCandidates = false); discovery = null
        // Serialize the cooling completion behind startup/stale relay cleanup and native zero.
        SessionShutdown.close(io, java.util.concurrent.Executor { main.post(it) },
            { oldRelay?.stop(); oldCandidates.clear(); forget?.let { vault.erase(it); if (it.secure) peerVault.erase(it) } }, afterClosed?.let { action -> { if (attempt == closingAttempt) action() } })
        CookieManager.getInstance().removeAllCookies(null); WebStorage.getInstance().deleteAllData(); showLobby()
    }
    private fun renderHealth(value: DeviceHealth) {
        val temperature = value.temperatureC?.let { String.format(java.util.Locale.ROOT, "%.1f°C", it) } ?: "온도 확인 불가"
        healthText.text = "배터리 ${value.batteryPct?.let { "$it%" } ?: "확인 불가"} · $temperature"
    }
    private fun showHealth(value: DeviceHealth) {
        val wasCooling = cooling.coolingRequired
        lastHealth = value; renderHealth(value)
        if (foreground && cooling.requestSleep(value)) sleepScreen(askPermission = false)
        else if (foreground && !sleeping && !cooling.coolingRequired) { if (wasCooling) screenPower.restore(); startDiscovery() }
    }
    private fun deviceDetails(candidate: Candidate? = lastSelectedCandidate) {
        val thermal = when (lastHealth?.thermalStatus) { 0 -> "정상"; 1 -> "가벼운 발열"; 2 -> "발열 주의"; 3, 4, 5, 6 -> "발열 보호"; else -> "상태 확인 불가" }
        pairingDialog?.dismiss()
        pairingDialog = AlertDialog.Builder(this).setTitle("기기·연결")
            .setMessage((candidate?.let { "${it.name}\n${it.host}\n\n" } ?: "") + "${healthText.text}\n발열: $thermal\n\n" + (session?.peerApproval?.let {
                "승인 관계: ${if (it.persistent) "지속 승인" else "기간 제한 (${it.authorizationExpiresAt})"}\n로그인: ${session?.expiresAt}까지\n승인 폐기는 수신 장치에서 확인하세요.\n\n"
            } ?: "") + "화면을 끄면 조종 연결을 닫습니다. 로봇은 다시 선택해 연결할 수 있습니다.")
            .setPositiveButton("화면 끄기") { _, _ -> sleepScreen(true) }.setNegativeButton("닫기", null)
            .apply { if (candidate != null) setNeutralButton("이 앱의 연결 기록 지우기") { _, _ -> forgetConnection(candidate) } }.create()
        pairingDialog!!.show()
    }
    private fun forgetConnection(candidate: Candidate) {
        pairingDialog = AlertDialog.Builder(this).setTitle("이 앱의 연결 기록 지우기")
            .setMessage("${candidate.name}\n${candidate.host}\n\n조종 연결을 닫고 이 태블릿에 저장된 로그인과 승인 연결 기록만 지웁니다. 수신 장치의 승인이나 다른 앱의 연결은 해제하지 않습니다.")
            .setNegativeButton("취소", null).setPositiveButton("지우기") { _, _ ->
                endSession(forget = candidate) {
                    lastSelectedCandidate = null; opening = false
                    lastError = "${candidate.name} · 이 태블릿의 연결 기록을 지웠습니다. 로봇을 선택하면 새 승인을 요청합니다."; startDiscovery()
                }; opening = true
            }.create()
        pairingDialog!!.show()
    }
    // D-456 4: an expired grant needs a separate receiver approval. Connect never sends one on its own;
    // the user asks here, which drops only this tablet's expired record and starts a fresh request.
    private fun reapprove(candidate: Candidate, reason: LinkReason) {
        pairingDialog?.dismiss()
        pairingDialog = AlertDialog.Builder(this).setTitle("다시 승인 요청")
            .setMessage("${candidate.name}\n\n" + (if (reason == LinkReason.APPROVAL_EXPIRED) "이 태블릿의 승인 사용 기한이 끝났습니다." else "로봇이 이 태블릿의 승인을 더 쓰지 않습니다(폐기·만료·권한 변경).") +
                " 새 승인을 요청하면 이 태블릿의 기록만 지우고 새 요청을 보냅니다. 로봇 화면 코드나 로봇 대시보드로 승인하세요.")
            .setNegativeButton("취소", null).setPositiveButton("승인 요청") { _, _ ->
                endSession(forget = candidate) { reselect = candidate; opening = false; startDiscovery() }; opening = true
            }.create()
        pairingDialog!!.show()
    }
    private fun returnToLobby() { endSession { opening = false; startDiscovery() }; opening = true }
    private fun backToLobbyOrExit() { if (web != null) returnToLobby() else finish() }
    @Deprecated("Handled by the platform back callback on API 33+")
    override fun onBackPressed() { backToLobbyOrExit() }
    private fun sleepScreen(askPermission: Boolean) {
        if (sleeping) return
        endSession {
            if (!screenSleep.finish(attempt) || isDestroyed || !foreground) return@endSession
            val locked = screenPower.sleep(askPermission)
            if (!locked) status.text = "조종 연결을 닫았습니다. 화면 잠금 승인이 없으면 Android 절전 시간 뒤 화면이 꺼집니다."
        }
        screenSleep.begin(attempt)
    }
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: android.content.Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == ScreenPower.REQUEST_SCREEN_LOCK && screenPower.approved()) pendingApprovedSleep = true
    }
    override fun onResume() {
        super.onResume(); foreground = true
        if (!cooling.coolingRequired) screenPower.restore()
        health.start()
        if (pendingApprovedSleep) { pendingApprovedSleep = false; sleepScreen(false) } else startDiscovery()
    }
    override fun onPause() { foreground = false; health.stop(); endSession(); super.onPause() }
    override fun onDestroy() { endSession(); io.execute { main.post { io.shutdown() } }; super.onDestroy() }
    companion object {
        fun readLimited(input: java.io.InputStream, maximum: Int): ByteArray {
            val out = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
            while (true) { val count = input.read(buffer); if (count < 0) break; require(out.size() + count <= maximum); out.write(buffer, 0, count) }
            return out.toByteArray()
        }
    }
}
