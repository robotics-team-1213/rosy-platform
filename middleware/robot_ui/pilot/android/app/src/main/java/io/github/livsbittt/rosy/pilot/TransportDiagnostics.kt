package io.github.livsbittt.rosy.pilot

internal class TransportDiagnostics(
    private val nowMs: () -> Long = { System.nanoTime() / 1_000_000 },
    private val emit: (String) -> Unit = {},
) {
    private data class Sample(var count: Long = 0, var localMs: Long = 0, var upstreamMs: Long = 0, var failures: Long = 0)
    private val names = listOf("control", "state", "video", "other")
    private val samples = Array(4) { Sample() }
    private var rejected = 0L
    private var closeCode = 0
    private var lastLogAt: Long? = null

    @Synchronized fun http(path: String, localMs: Long, upstreamMs: Long, status: Int) {
        val kind = when {
            path == "/api/v1/teleop" -> 0
            path == "/api/v1/robot/state" -> 1
            path.startsWith("/api/v1/vision/") -> 2
            else -> 3
        }
        samples[kind].apply {
            count++; this.localMs = localMs.coerceAtLeast(0); this.upstreamMs = upstreamMs.coerceAtLeast(0)
            if (status == 0 || status >= 400) failures++
        }
        publish()
    }
    @Synchronized fun rejected() { rejected++; publish() }
    @Synchronized fun streamFailed() { samples[2].failures++; publish() }
    @Synchronized fun socketClosed(code: Int) { closeCode = if (code in 1000..4999) code else 0; publish() }
    @Synchronized fun summary(): String = samples.mapIndexed { index, value ->
        "${names[index]} count=${value.count} local_ms=${value.localMs} upstream_ms=${value.upstreamMs} failures=${value.failures}"
    }.joinToString("; ") + "; background_rejected=$rejected ws_close=$closeCode"

    @Synchronized fun display(): String = samples.mapIndexed { index, value ->
        "${listOf("조작", "상태", "영상", "기타")[index]}: 앱 처리 ${value.localMs}ms · 로봇 첫 응답 ${value.upstreamMs}ms · 오류 ${value.failures}/${value.count}"
    }.joinToString("\n") + "\n혼잡으로 미룬 조회 $rejected · 마지막 소켓 종료 $closeCode"

    private fun publish() {
        val now = nowMs()
        if (lastLogAt == null || now - lastLogAt!! >= 5000) {
            lastLogAt = now
            runCatching { emit(summary()) }
        }
    }
}
