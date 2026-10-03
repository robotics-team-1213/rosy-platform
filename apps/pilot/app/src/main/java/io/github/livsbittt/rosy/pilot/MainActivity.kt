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

/** Discover, select, join. A code appears only when the selected server requires pairing. */
class MainActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private val vault by lazy { PairingVault(this) }
    private var candidates = CandidateStore()
    private var discovery: RobotDiscovery? = null
    private var proxy: PilotProxy? = null
    private var web: WebView? = null
    private var pairingDialog: AlertDialog? = null
    @Volatile private var session: LobbySession? = null
    @Volatile private var attempt = 0L
    private var foreground = false
    private var opening = false
    private lateinit var root: LinearLayout
    private lateinit var status: TextView
    private lateinit var robots: LinearLayout
    private val refreshTick = object : Runnable {
        override fun run() { if (!foreground) return; refresh(); if (foreground) main.postDelayed(this, 5000) }
    }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state); window.addFlags(WindowManager.LayoutParams.FLAG_SECURE); showLobby()
    }
    private fun label(text: String, size: Float = 18f) = TextView(this).apply {
        this.text = text; textSize = size; setTextColor(PilotColors.foreground); setPadding(0, 12, 0, 12)
    }
    private fun button(text: String, action: () -> Unit) = Button(this).apply {
        this.text = text; isAllCaps = false; textSize = 18f; setPadding(24, 12, 24, 12)
        setTextColor(android.content.res.ColorStateList(arrayOf(intArrayOf(android.R.attr.state_enabled), intArrayOf()), intArrayOf(PilotColors.foreground, PilotColors.muted)))
        fun fill(color: Int) = android.graphics.drawable.GradientDrawable().apply { setColor(color); cornerRadius = 12f; setStroke(1, PilotColors.muted) }
        background = android.graphics.drawable.StateListDrawable().apply {
            addState(intArrayOf(-android.R.attr.state_enabled), fill(PilotColors.disabled))
            addState(intArrayOf(android.R.attr.state_pressed), fill(PilotColors.pressed))
            addState(intArrayOf(), fill(PilotColors.card))
        }
        setOnClickListener { action() }
    }
    private fun showLobby() {
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 16, 32, 16); setBackgroundColor(PilotColors.background) }
        setContentView(root)
        window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        root.addView(label("ROSY", 24f).apply { setTextColor(PilotColors.rose) })
        root.addView(label("Pilot · 로봇 선택", 26f))
        status = label("같은 Wi-Fi에서 켜진 로봇을 찾고 있습니다…"); root.addView(status)
        root.addView(button("다시 찾기") { endSession(); startDiscovery() })
        robots = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(ScrollView(this).apply { addView(robots) }, LinearLayout.LayoutParams(-1, 0, 1f))
    }
    private fun startDiscovery() {
        if (!foreground || discovery != null) return
        discovery = RobotDiscovery(this, candidates) { main.post { refresh() } }
        runCatching { discovery!!.start() }.onFailure { status.text = "Wi-Fi 연결을 확인한 뒤 다시 찾아주세요." }
        main.removeCallbacks(refreshTick); main.postDelayed(refreshTick, 5000)
    }
    private fun refresh() {
        val current = session
        if (current != null && !current.authorized()) {
            endSession(); status.text = "연결이 끝났습니다. 로봇을 다시 선택하세요."; startDiscovery(); return
        }
        if (web != null || opening) return
        robots.removeAllViews()
        val records = candidates.records()
        if (records.isEmpty()) { robots.addView(label("로봇이 보이지 않습니다. 같은 Wi-Fi와 로봇 전원을 확인하세요.", 16f)); return }
        status.text = "로봇을 눌러 연결하세요. 필요한 경우에만 로봇의 로그인 코드를 입력합니다."
        records.forEach { candidate ->
            val valid = runCatching { candidates.addresses(candidate.host, candidate.port) != null }.getOrDefault(false)
            robots.addView(button("${candidate.name.ifBlank { candidate.robotId.ifBlank { "Rosy" } }} · ${if (valid) "연결" else "중복 광고 확인"}") {
                select(candidate)
            }.apply { isEnabled = valid })
        }
    }
    private fun select(incoming: Candidate) {
        if (opening || web != null) return
        val addresses = runCatching { candidates.addresses(incoming.host, incoming.port) }.getOrNull() ?: return
        val candidate = incoming.copy(addresses = addresses)
        opening = true
        val version = ++attempt; val store = candidates
        for (i in 0 until robots.childCount) robots.getChildAt(i).isEnabled = false
        status.text = "${candidate.name} · 연결 확인 중…"
        io.execute {
            if (attempt != version) return@execute
            try {
                val offer = LobbyPairing.offer(candidate)
                val saved = if (offer.mode == "paired") vault.load(candidate, offer, store) else null
                val reused = saved?.takeIf { LobbyPairing.reuse(it) }
                if (saved != null && reused == null) vault.erase(candidate)
                main.post {
                    if (version != attempt || !foreground) return@post
                    if (reused != null) join(candidate, offer, store, version, null, reused)
                    else if (offer.mode == "development") join(candidate, offer, store, version, null)
                    else pairingCode(candidate, offer, store, version)
                }
            } catch (_: Exception) { failed(version, "연결할 수 없습니다. 로봇 서비스·신뢰된 HTTPS 연결을 확인하세요.") }
        }
    }
    private fun pairingCode(candidate: Candidate, offer: LobbyOffer, store: CandidateStore, version: Long) {
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val input = EditText(this).apply {
            hint = "8자리 로그인 코드"; textSize = 28f; setSingleLine(); setTextColor(PilotColors.foreground)
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS or android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            filters = arrayOf(android.text.InputFilter.LengthFilter(8))
        }
        fun canceled() { if (version == attempt) { opening = false; refresh() } }
        val dialog = AlertDialog.Builder(this).setTitle("로봇 로그인 코드")
            .setMessage("${candidate.name}에 표시된 숫자·영문 코드를 입력하세요.").setView(input)
            .setPositiveButton("연결", null).setNegativeButton("취소") { _, _ -> canceled() }
            .setOnCancelListener { canceled() }.create()
        pairingDialog = dialog
        dialog.setOnDismissListener { if (pairingDialog === dialog) pairingDialog = null; if (web == null) window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) }
        dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val code = input.text.toString().trim().uppercase()
            if (!Regex("[0-9A-Z]{8}").matches(code)) { input.error = "숫자·영문 8자리"; return@setOnClickListener }
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
                if (offer.mode == "paired") approved.onInvalidated = { vault.erase(candidate) }
                if (version != attempt) return@execute
                relay = PilotProxy(approved, AssetBundle(assets)) { message -> main.post { if (version == attempt) status.text = message } }
                relay.verifyIdentity(); relay.start(5000, false)
                if (offer.mode == "paired" && version == attempt) vault.save(candidate, approved)
                val ready = relay
                main.post {
                    if (version != attempt || !foreground || web != null) { io.execute { ready.stop() }; return@post }
                    opening = false; session = approved; proxy = ready
                    root.removeView(robots.parent as View)
                    root.addView(button("로봇 목록으로") { endSession(); startDiscovery() })
                    val view = WebView(this); web = view; view.setBackgroundColor(PilotColors.background)
                    view.webChromeClient = object : android.webkit.WebChromeClient() {
                        override fun onConsoleMessage(message: android.webkit.ConsoleMessage): Boolean {
                            android.util.Log.e("RosyPilot", "Web console ${message.messageLevel()} ${message.sourceId().substringBefore('?')} line ${message.lineNumber()}")
                            return true
                        }
                    }
                    window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
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
                    status.text = "${candidate.name} · ${if (offer.mode == "development") "개발 모드" else "연결됨"}"
                }
            } catch (error: Exception) {
                // Exception messages and HTTP bodies can contain credentials; log class and locations only.
                android.util.Log.e("RosyPilot", "Join failed: ${error.javaClass.simpleName}\n" + error.stackTrace.take(8).joinToString("\n"))
                relay?.stop(); failed(version, "연결하지 못했습니다. 코드를 확인하거나 잠시 뒤 다시 선택하세요.")
            }
        }
    }
    private fun failed(version: Long, message: String) { main.post {
        if (version != attempt || !foreground) return@post
        opening = false; refresh(); status.text = message
    } }
    private fun endSession() {
        // Resource-owning completion callbacks must run their stale-attempt cleanup.
        attempt++; opening = false; main.removeCallbacks(refreshTick)
        pairingDialog?.dismiss(); pairingDialog = null
        web?.evaluateJavascript("window.dispatchEvent(new Event('blur')); sessionStorage.clear();", null)
        web?.stopLoading(); web?.destroy(); web = null
        val oldRelay = proxy; proxy = null; session = null
        val oldCandidates = candidates; candidates = CandidateStore()
        discovery?.stop(clearCandidates = false); discovery = null
        if (oldRelay != null) io.execute { oldRelay.stop(); oldCandidates.clear() } else oldCandidates.clear()
        CookieManager.getInstance().removeAllCookies(null); WebStorage.getInstance().deleteAllData(); showLobby()
    }
    override fun onResume() { super.onResume(); foreground = true; startDiscovery() }
    override fun onPause() { foreground = false; endSession(); super.onPause() }
    override fun onDestroy() { endSession(); io.execute { main.post { io.shutdown() } }; super.onDestroy() }
    companion object {
        fun readLimited(input: java.io.InputStream, maximum: Int): ByteArray {
            val out = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
            while (true) { val count = input.read(buffer); if (count < 0) break; require(out.size() + count <= maximum); out.write(buffer, 0, count) }
            return out.toByteArray()
        }
    }
}
