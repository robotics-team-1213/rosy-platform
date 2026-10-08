package io.github.livsbittt.rosy.pilot

import android.app.Activity
import android.app.AlertDialog
import android.os.Handler
import android.os.Looper
import android.text.InputFilter
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** The activity's attempt owns this dialog and transaction; background/cancel never approves a fingerprint. */
class PeerApprovalUi(private val activity: Activity, private val signer: () -> PeerSigner,
    private val vault: PeerRelationshipVault) {
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var client: PeerClient? = null
    @Volatile private var answer: CountDownLatch? = null
    @Volatile private var accepted = false
    private val owner = java.util.concurrent.atomic.AtomicLong()
    private var dialog: AlertDialog? = null
    fun close() {
        owner.incrementAndGet(); client?.close(); client = null; accepted = false; answer?.countDown()
        dialog?.dismiss(); dialog = null
    }
    /** Runs on the existing IO executor; the UI thread remains available for cancellation/health shutdown. */
    fun connect(candidate: Candidate, store: CandidateStore, current: () -> Boolean, canceled: () -> Unit): LobbySession? {
        val version = owner.incrementAndGet()
        fun owns() = owner.get() == version && current()
        val flow = PeerClient(candidate, store, signer(), vault, current = ::owns)
        client = flow
        try {
            return flow.connect(onPending = { pending -> main.post {
                if (!owns()) return@post
                activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                val message = LinkStatus.pending("${candidate.name} · ${pending.receiverId}", pending.code,
                    java.time.Duration.between(java.time.Instant.now(), pending.expiresAt).seconds, pending.caSha256)
                if (dialog == null) {
                    val code = EditText(activity).apply {
                        // D-483 M1: the LCD may list several requests; ours is the line with our display code.
                        hint = "로봇 화면에서 ${pending.code} 옆의 승인 코드"
                        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
                        filters = arrayOf(InputFilter.AllCaps(), InputFilter.LengthFilter(6))
                    }
                    val note = TextView(activity)
                    val form = LinearLayout(activity).apply {
                        orientation = LinearLayout.VERTICAL; setPadding(48, 0, 48, 0); addView(code); addView(note)
                    }
                    dialog = AlertDialog.Builder(activity).setTitle("승인 대기 · ${pending.code}")
                        .setMessage(message).setView(form)
                        .setPositiveButton("승인 코드 확인", null)
                        .setNegativeButton("취소") { _, _ -> close(); canceled() }
                        .setOnCancelListener { close(); canceled() }.create()
                    dialog!!.show()
                    val send = dialog!!.getButton(AlertDialog.BUTTON_POSITIVE)
                    // D-483: the dialog stays open; the status poll closes it once the request is approved.
                    send.setOnClickListener {
                        val typed = code.text.toString().trim().uppercase()
                        if (!PeerClient.APPROVAL_CODE.matches(typed)) { note.text = "승인 코드는 로봇 화면의 6자입니다."; return@setOnClickListener }
                        send.isEnabled = false; note.text = "승인 코드를 확인하는 중입니다."
                        Thread {
                            val outcome = runCatching { flow.confirm(typed) }.exceptionOrNull()
                            main.post {
                                if (!owns()) return@post
                                send.isEnabled = true
                                note.text = when {
                                    outcome == null -> "승인 코드를 보냈습니다. 연결을 마무리합니다."
                                    outcome is PeerCodeWrong && outcome.remaining == 0 -> "승인 코드가 5번 틀려 요청이 거절되었습니다."
                                    outcome is PeerCodeWrong -> "승인 코드가 맞지 않습니다. 남은 시도 ${outcome.remaining}번"
                                    outcome is PeerRefused && outcome.status == 404 -> {
                                        code.visibility = View.GONE; send.visibility = View.GONE
                                        "이 로봇은 콘솔 승인만 지원합니다"
                                    }
                                    outcome is PeerRefused && outcome.status == 429 -> "틀린 승인 코드가 많아 잠시 화면 코드를 받지 않습니다. 로봇 대시보드에서 승인하세요."
                                    outcome is PeerRefused && outcome.status == 403 -> "화면 코드는 조종 권한까지만 승인합니다. 로봇 대시보드에서 승인하세요."
                                    LinkStatus.unreachable(outcome) -> "로봇에 닿지 않아 코드를 보내지 못했습니다. Wi-Fi를 확인하고 다시 입력하세요."
                                    else -> "승인 코드를 보내지 못했습니다. 다시 입력하거나 로봇 대시보드에서 승인하세요."
                                }
                            }
                        }.start()
                    }
                }
                dialog!!.setMessage(message)
            } }, confirmCa = { offer ->
                accepted = false
                val latch = CountDownLatch(1); answer = latch
                main.post {
                    if (!owns()) { latch.countDown(); return@post }
                    dialog?.dismiss()
                    // D-483 2026-10-09: the LCD draws the first 16 digits as "CA xxxx xxxx xxxx xxxx"; the dashboard shows all 64.
                    dialog = AlertDialog.Builder(activity).setTitle("승인됨 · 로봇 인증서 확인")
                        .setMessage("${candidate.name} · ${offer.hostname}\n\n처음 연결하는 로봇입니다. 아래 값이 로봇 쪽 표시와 같은지 확인하세요.\n\n" +
                            "승인 대기 중 로봇 화면 'CA' 줄과 비교한 값:\nCA ${LinkStatus.caShort(offer.sha256)}\n\n" +
                            "또는 로봇 대시보드의 인증서 확인 값 전체와 비교:\n${offer.sha256.chunked(4).joinToString(" ")}\n\n" +
                            "어느 쪽에서도 같은 값을 확인하지 못했으면 연결하지 마세요.")
                        .setPositiveButton("표시가 같습니다") { _, _ -> if (owns()) accepted = true; latch.countDown() }
                        .setNegativeButton("다릅니다 · 취소") { _, _ -> close(); canceled() }
                        .setOnCancelListener { close(); canceled() }.create()
                    dialog!!.show()
                }
                val finished = latch.await(120, TimeUnit.SECONDS)
                answer = null
                finished && owns() && accepted
            })
        } finally {
            if (client === flow) client = null
            main.post { if (owner.get() == version) { dialog?.dismiss(); dialog = null; activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) } }
        }
    }
}
