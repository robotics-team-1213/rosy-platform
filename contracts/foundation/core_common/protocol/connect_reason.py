"""D-535 connection failure reasons: one code, an operator message and a recovery action.

The machine source is ``test/fixtures/protocol/connect-reasons.v1.json``; this module
must equal it (contract test). CORE puts these codes in ERR-101 bodies of the
connection, pairing and session routes. A client turns every failure that never
reached the robot (name, TCP, TLS) and every older robot's answer into the same codes
with ``classify``. D-370 failure classes stay the retry policy; a reason is what a
person reads. Standard library only.
"""

from __future__ import annotations

#: code -> (retry, message, action). HTTP statuses stay what each route already returns.
#: retry "auto": the client may retry by itself with backoff; "person": a person must act first.
REASONS = {
    "ROBOT_UNREACHABLE": ("auto", "로봇에 닿지 않습니다.",
                          "로봇 전원과 Wi-Fi를 확인하고, 이 기기가 로봇과 같은 Wi-Fi에 있는지 보세요."),
    "TLS_REQUIRED": ("person", "이 로봇은 HTTPS 연결만 받습니다.",
                     "로봇 이름 주소(https://rosy-pinky-xxxx.local:8080)로 다시 연결하세요."),
    "TLS_NAME_MISMATCH": ("person", "로봇 인증서의 이름이 연결한 주소와 다릅니다.",
                          "IP 주소 대신 로봇 이름 주소(rosy-pinky-xxxx.local)로 연결하세요."),
    "CA_UNKNOWN": ("person", "이 기기가 로봇 인증서를 아직 믿지 않습니다.",
                   "로봇을 목록에서 지우고 다시 승인받아 로봇 인증서를 새로 받으세요."),
    "CORE_NOT_READY": ("auto", "로봇은 켜져 있지만 CORE가 아직 준비되지 않았습니다.",
                       "1분쯤 기다리세요. 계속되면 로봇 화면의 상태를 확인하세요."),
    "API_VERSION_TOO_OLD": ("person", "로봇 소프트웨어가 이 앱보다 오래되었습니다.",
                            "로봇을 최신 릴리스로 업데이트하세요."),
    "PAIRING_UNAVAILABLE": ("person", "이 로봇은 지금 기기 승인을 받을 수 없습니다.",
                            "관리자에게 로봇의 HTTPS 설정과 상태를 확인해 달라고 하세요."),
    "PAIRING_REQUIRED": ("person", "이 기기는 이 로봇에 승인되어 있지 않습니다.",
                         "로봇에 연결을 다시 요청하고 승인을 받으세요."),
    "IDENTITY_CHANGED": ("person", "로봇의 신원 키가 기억한 것과 다릅니다. 연결을 막았습니다.",
                         "로봇을 다시 설치한 것이 확실할 때만 연결 기록을 지우고 다시 승인받으세요. 모르면 관리자에게 알리세요."),
    "LAN_REQUIRED": ("person", "처음 승인은 로봇과 같은 Wi-Fi에서만 요청할 수 있습니다.",
                     "로봇과 같은 Wi-Fi에 연결한 뒤 다시 요청하세요."),
    "APPROVAL_PENDING": ("auto", "승인을 기다리는 중입니다.",
                         "로봇 화면의 승인 코드를 입력하거나 관제에서 승인을 받으세요."),
    "APPROVAL_CODE_WRONG": ("person", "승인 코드가 맞지 않습니다.",
                            "로봇 화면의 6자 코드를 다시 확인해 입력하세요."),
    "CONSOLE_APPROVAL_REQUIRED": ("person", "이 요청은 로봇 화면 코드로 승인할 수 없습니다.",
                                  "관제(Fleet) 또는 로봇 대시보드에서 관리자가 승인해야 합니다."),
    "APPROVAL_TIMEOUT": ("person", "승인 요청이 시간 안에 승인되지 않아 끝났습니다.",
                         "로봇을 다시 선택해 새 요청을 보내세요."),
    "APPROVAL_CANCELLED": ("person", "승인 요청이 취소되었습니다.",
                           "로봇을 다시 선택해 새 요청을 보내세요."),
    "APPROVAL_EXPIRED": ("person", "승인 사용 기한이 끝났습니다.",
                         "로봇에 연결을 다시 요청해 승인받으세요."),
    "APPROVAL_DENIED": ("person", "승인이 거절되었습니다(관제에서 거절했거나 승인 코드가 5번 틀림).",
                        "관리자에게 확인한 뒤 새 요청을 보내세요."),
    "APPROVAL_REVOKED": ("person", "로봇이 이 기기의 승인을 더 쓰지 않습니다(폐기 또는 승인한 관리자 권한 변경).",
                         "관리자에게 확인한 뒤 다시 승인받으세요."),
    "RATE_LIMITED": ("auto", "요청이 너무 잦습니다.",
                     "안내된 시간(Retry-After)만큼 기다린 뒤 다시 시도하세요."),
    "SESSION_TAKEN": ("person", "다른 사람이 이 로봇을 쥐고 있습니다.",
                      "지금 쥔 사람에게 끝내 달라고 하거나 끝날 때까지 기다리세요."),
    "UNEXPECTED_RESPONSE": ("person", "로봇이 예상하지 못한 답을 했습니다.",
                            "앱 로그를 남겨 담당자에게 알리세요."),
}

#: Transport failures before any HTTP answer (closed vocabulary).
TRANSPORT = {
    "dns_failure": "ROBOT_UNREACHABLE",
    "timeout": "ROBOT_UNREACHABLE",
    "no_route": "ROBOT_UNREACHABLE",
    # A host that answers TCP with a reset has no CORE listener on the port yet.
    "connection_refused": "CORE_NOT_READY",
    "plain_http_to_tls": "TLS_REQUIRED",
    "tls_name_mismatch": "TLS_NAME_MISMATCH",
    "tls_unknown_ca": "CA_UNKNOWN",
    "tls_pin_mismatch": "CA_UNKNOWN",
    "tls_handshake": "CA_UNKNOWN",
}

#: Existing ERR-101 codes that already mean a connection reason.
ROBOT_CODES = {
    "UNAUTHORIZED": "PAIRING_REQUIRED",
    "PAIRING_INVALID": "PAIRING_REQUIRED",
    # D-460: CORE has no Pilot seat; the calibration lease is the robot's "held by another token".
    "CALIBRATION_ACTIVE": "SESSION_TAKEN",
    "ROBOT_OFFLINE": "ROBOT_UNREACHABLE",
    "HARDWARE_NOT_READY": "CORE_NOT_READY",
}

#: An answer without a known code (older robots): HTTP status alone.
HTTP_STATUS = {
    401: "PAIRING_REQUIRED",
    404: "API_VERSION_TOO_OLD",
    409: "PAIRING_REQUIRED",
    429: "RATE_LIMITED",
    503: "CORE_NOT_READY",
}
HTTP_5XX_FALLBACK = "CORE_NOT_READY"
HTTP_FALLBACK = "UNEXPECTED_RESPONSE"

#: A D-456 request status read (200) whose state is not usable yet.
REQUEST_STATES = {
    "pending": "APPROVAL_PENDING",
    "rejected": "APPROVAL_DENIED",
    "expired": "APPROVAL_TIMEOUT",
    "cancelled": "APPROVAL_CANCELLED",
}


def classify(*, transport: str | None = None, http_status: int | None = None,
             code: str | None = None, request_state: str | None = None,
             authorization_available: bool | None = None) -> str | None:
    """Return the reason for exactly one observation, or None when it is not a failure.

    ``code`` (an ERR-101 ``error.code``) wins over ``http_status`` when both come from
    one answer. Unknown transport and request-state values raise ValueError.
    """
    if transport is not None:
        if transport not in TRANSPORT:
            raise ValueError(f"unknown transport failure {transport!r}")
        return TRANSPORT[transport]
    if request_state is not None:
        if request_state == "approved":
            return None if authorization_available is not False else "APPROVAL_EXPIRED"
        if request_state not in REQUEST_STATES:
            raise ValueError(f"unknown request state {request_state!r}")
        return REQUEST_STATES[request_state]
    if code in REASONS:
        return code
    if code in ROBOT_CODES:
        return ROBOT_CODES[code]
    if http_status is None:
        raise ValueError("one of transport, request_state, code or http_status is required")
    if http_status < 400:
        return None
    if http_status in HTTP_STATUS:
        return HTTP_STATUS[http_status]
    return HTTP_5XX_FALLBACK if http_status >= 500 else HTTP_FALLBACK


def body(code: str, detail: dict | None = None) -> dict:
    """ERR-101 body for a reason, with the operator message and recovery action."""
    retry, message, action = REASONS[code]
    return {"error": {"code": code, "message": message,
                      "detail": {**(detail or {}), "action": action, "retry": retry}}}
