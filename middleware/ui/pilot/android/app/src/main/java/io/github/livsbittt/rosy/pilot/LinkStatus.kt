package io.github.livsbittt.rosy.pilot

/**
 * Why a robot link did not come up. Names follow the connection-failure reason codes
 * (ROBOT_UNREACHABLE, CA_UNKNOWN, APPROVAL_*, RATE_LIMITED, CORE_NOT_READY, API_VERSION_TOO_OLD);
 * [LinkStatus.reason] is the single place that maps a client failure (or later a server code) onto them.
 */
enum class LinkReason {
    ROBOT_UNREACHABLE, CA_UNKNOWN, IDENTITY_CHANGED, APPROVAL_EXPIRED, APPROVAL_TIMEOUT, APPROVAL_DENIED,
    APPROVAL_CANCELLED, APPROVAL_REVOKED, API_VERSION_TOO_OLD, CORE_NOT_READY, RATE_LIMITED, REFUSED, UNKNOWN
}

/** What the lobby says for each reason, with the next action, so it never shows a bare "cannot connect". */
object LinkStatus {
    /** The one mapping point from a failure to its reason (a server-sent code can replace these guesses). */
    fun reason(error: Throwable): LinkReason = when {
        error is PeerApprovalExpired -> LinkReason.APPROVAL_EXPIRED
        error is PeerApprovalTimeout -> LinkReason.APPROVAL_TIMEOUT
        error is PeerEnded && error.state == "rejected" -> LinkReason.APPROVAL_DENIED
        error is PeerEnded && error.state == "expired" -> LinkReason.APPROVAL_TIMEOUT
        error is PeerEnded && error.state == "cancelled" -> LinkReason.APPROVAL_CANCELLED
        error is PeerKeyChanged -> LinkReason.IDENTITY_CHANGED
        error is PeerRefused && error.status == 404 -> LinkReason.API_VERSION_TOO_OLD
        error is PeerRefused && error.status == 503 -> LinkReason.CORE_NOT_READY
        error is PeerRefused && error.status == 429 -> LinkReason.RATE_LIMITED
        error is PeerRefused && error.status in setOf(401, 403, 409) -> LinkReason.APPROVAL_REVOKED
        error is PeerRefused -> LinkReason.REFUSED
        unreachable(error) -> LinkReason.ROBOT_UNREACHABLE
        error is javax.net.ssl.SSLException -> LinkReason.CA_UNKNOWN
        else -> LinkReason.UNKNOWN
    }

    /** What the lobby shows: the cause and the next action. Never an exception message (may carry credentials). */
    fun failure(error: Throwable, secure: Boolean): String = when (reason(error)) {
        LinkReason.APPROVAL_EXPIRED -> "승인 사용 기한이 끝났습니다. '승인 요청'을 눌러 다시 승인받으세요."
        LinkReason.APPROVAL_TIMEOUT -> "승인 요청이 시간 안에 승인되지 않아 끝났습니다. 로봇을 다시 선택해 새 요청을 보내세요."
        LinkReason.APPROVAL_DENIED -> "로봇이 요청을 거절했습니다(콘솔에서 거절했거나 승인 코드가 5번 틀림). 로봇을 다시 선택해 새 요청을 보내세요."
        LinkReason.APPROVAL_CANCELLED -> "승인 요청이 취소되었습니다. 로봇을 다시 선택해 새 요청을 보내세요."
        LinkReason.IDENTITY_CHANGED -> "로봇의 신원 키가 기억한 것과 다릅니다. 연결을 막았습니다. 로봇을 다시 설치한 것이 확실할 때만 '기기·연결'에서 이 앱의 연결 기록을 지우고, 모르면 지우지 말고 관리자에게 알리세요."
        LinkReason.API_VERSION_TOO_OLD -> "로봇 소프트웨어가 오래되어 앱 승인 연결을 지원하지 않습니다. 로봇을 새 릴리스로 업데이트해야 합니다."
        LinkReason.CORE_NOT_READY -> "로봇 CORE가 아직 준비되지 않았습니다. 잠시 뒤 로봇을 다시 선택하세요."
        LinkReason.RATE_LIMITED -> "연결 요청이 너무 많습니다. 1분 뒤 다시 선택하세요."
        LinkReason.APPROVAL_REVOKED -> "로봇이 이 태블릿의 승인을 더 쓰지 않습니다(폐기·만료·권한 변경). '기기·연결'에서 이 앱의 연결 기록을 지운 뒤 다시 승인받으세요."
        LinkReason.REFUSED -> "로봇이 연결을 거절했습니다(HTTP ${(error as PeerRefused).status}). 로봇을 다시 선택하세요. 계속되면 로봇 대시보드를 확인하세요."
        LinkReason.ROBOT_UNREACHABLE -> "로봇에 닿지 않습니다. 로봇 전원이 켜져 있고 태블릿과 같은 Wi-Fi인지 확인한 뒤 다시 선택하세요."
        LinkReason.CA_UNKNOWN -> "로봇의 HTTPS 인증서를 확인할 수 없습니다. 연결을 막았습니다. 로봇을 다시 설치한 것이 확실할 때만 '기기·연결'에서 이 앱의 연결 기록을 지우고, 모르면 지우지 말고 관리자에게 알리세요."
        LinkReason.UNKNOWN -> if (secure) "연결을 마치지 못했습니다. 로봇을 다시 선택하세요. 계속되면 로봇 대시보드에서 상태를 확인하세요."
            else "연결할 수 없습니다. 로봇 전원과 같은 Wi-Fi 연결을 확인한 뒤 다시 선택하세요."
    }

    /** Connection refused, timed out, no route or name: the robot is off, asleep or on another network. */
    fun unreachable(error: Throwable): Boolean = generateSequence(error) { it.cause }.take(8).any {
        it is java.net.ConnectException || it is java.net.SocketTimeoutException || it is java.net.NoRouteToHostException ||
            it is java.net.UnknownHostException || it is java.io.InterruptedIOException && it.message == "timeout"
    }

    /** The pending line: which request, how long it stays, both ways to approve, and what an old robot looks like. */
    fun pending(robot: String, displayCode: String, secondsLeft: Long, caSha256: String? = null): String {
        val left = secondsLeft.coerceAtLeast(0)
        return "$robot\n\n상태: 승인 대기 · 요청 번호 $displayCode · 남은 시간 ${left / 60}:${"%02d".format(left % 60)}\n\n" +
            "승인 방법 (먼저 끝난 쪽이 승인합니다)\n" +
            "1) 로봇 화면 'Pair request'의 $displayCode 줄 옆 6자를 아래에 입력\n" +
            (caSha256?.let { "   먼저 로봇 화면 맨 아래 줄이 CA ${caShort(it)} 인지 확인하세요. 다르면 입력하지 말고 취소하세요.\n" } ?: "") +
            "2) 로봇 대시보드(관리자)에서 요청 $displayCode 승인\n\n" +
            "로봇 화면에 'Pair request'가 없으면 이 로봇 릴리스는 화면 코드를 보이지 못합니다. 2)로 승인하거나 로봇 업데이트를 요청하세요.\n" +
            "요청 범위: 조종(operator) · 관리자 권한은 주지 않습니다."
    }

    /** First 16 hex digits in fours: exactly what the robot LCD's "CA" line draws. */
    fun caShort(sha256: String): String = sha256.take(16).chunked(4).joinToString(" ")
}
