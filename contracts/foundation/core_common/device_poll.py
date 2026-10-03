"""공통 HTTP 폴링 유틸리티 — 외부 장비(도크·신호등·센서)가 같은 패턴으로 통신한다.

D-352: 폴링 실패 어휘를 통일한다 (unreachable/timeout/bad_response/ok).
D-353: 새 장비가 이 함수를 호출하면 패턴이 자동으로 통일된다.

표준 라이브러리만 쓴다 — HTTP 클라이언트 의존성을 추가하지 않는다
(도크 agent가 `install_requires=['setuptools']` 제약을 지키기 위함).
"""

from __future__ import annotations

import enum
import json
import socket
import urllib.error
import urllib.request
from typing import Any, Optional


class PollReachability(str, enum.Enum):
    """외부 장비 폴링 결과. 실패 사유를 구분하는 것이 존재 이유다.

    "장비가 거짓말을 했다"와 "장비가 말을 안 했다"가 같은 값이면
    재시도 전략을 세울 수 없다 (D-352).
    """

    OK = "ok"
    UNREACHABLE = "unreachable"      # 주소 없음, 연결 거부, DNS 실패
    TIMEOUT = "timeout"              # 응답이 제때 오지 않음
    BAD_RESPONSE = "bad_response"    # 200이 아니거나, JSON이 아니거나, 필드 누락


def poll_json(
    url: str,
    *,
    timeout_s: float = 1.0,
    required_fields: tuple[str, ...] = (),
) -> tuple[PollReachability, Optional[dict[str, Any]], Optional[str]]:
    """외부 장비에 한 번 묻는다. 절대 예외를 올리지 않고 절대 timeout 보다 오래 막지 않는다.

    Returns:
        (reachability, parsed_json_or_None, error_message_or_None)
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            if response.status != 200:
                return PollReachability.BAD_RESPONSE, None, f"http {response.status}"
            raw = response.read()
    except socket.timeout:
        return PollReachability.TIMEOUT, None, "timed out"
    except urllib.error.HTTPError as error:
        return PollReachability.BAD_RESPONSE, None, f"http {error.code}"
    except urllib.error.URLError as error:
        if isinstance(error.reason, socket.timeout):
            return PollReachability.TIMEOUT, None, "timed out"
        return PollReachability.UNREACHABLE, None, str(error.reason)
    except OSError as error:
        return PollReachability.UNREACHABLE, None, str(error)

    try:
        document: Any = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        return PollReachability.BAD_RESPONSE, None, f"unparseable: {error}"

    if not isinstance(document, dict):
        return PollReachability.BAD_RESPONSE, None, "body is not an object"

    missing = [key for key in required_fields if key not in document]
    if missing:
        return (PollReachability.BAD_RESPONSE, None,
                f"missing field(s): {', '.join(missing)}")

    return PollReachability.OK, document, None
