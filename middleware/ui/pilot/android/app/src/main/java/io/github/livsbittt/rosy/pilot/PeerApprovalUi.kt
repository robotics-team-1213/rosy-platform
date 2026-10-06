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
                val message = "${candidate.name} · ${pending.receiverId}\n\n로봇 화면에 뜬 승인 코드를 입력하거나 수신 화면에서 Rosy Pilot의 연결 요청을 승인하세요.\n요청 범위: 조종 화면 · 기존 안전 규칙과 사용 권한 유지\n요청 확인: ${pending.code}\n\n4문자는 요청을 찾는 표시입니다. 조종이나 관리자 권한을 발급하지 않습니다."
                if (dialog == null) {
                    val code = EditText(activity).apply {
                        hint = "로봇 화면의 승인 코드"
                        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
                        filters = arrayOf(InputFilter.AllCaps(), InputFilter.LengthFilter(6))
                    }
                    val note = TextView(activity)
                    val form = LinearLayout(activity).apply {
                        orientation = LinearLayout.VERTICAL; setPadding(48, 0, 48, 0); addView(code); addView(note)
                    }
                    dialog = AlertDialog.Builder(activity).setTitle("수신 장치 승인 대기")
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
                                    outcome is PeerCodeWrong -> "승인 코드가 맞지 않습니다." + (outcome.remaining?.let { " 남은 시도 ${it}번" } ?: "")
                                    outcome is PeerRefused && outcome.status == 404 -> {
                                        code.visibility = View.GONE; send.visibility = View.GONE
                                        "이 로봇은 콘솔 승인만 지원합니다"
                                    }
                                    else -> "승인 코드를 보내지 못했습니다. 다시 입력하거나 수신 화면에서 승인하세요."
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
                    dialog = AlertDialog.Builder(activity).setTitle("수신 화면의 인증서 확인")
                        .setMessage("${candidate.name} · ${offer.hostname}\n\n수신 장치의 승인 화면과 아래 인증서 확인 값 전체가 같은지 확인하세요.\n\n${offer.sha256.chunked(8).joinToString(" ")}\n\n이름이나 4문자만 같아도 연결하지 마세요.")
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
