"""core_features.docking.agent — 도크 상태를 묻는 클라이언트 (DNC-004).

**로봇이 폴링한다. 도크는 먼저 말을 걸지 않는다.** 도크는 어느 로봇이 다가오는지
모르지만 로봇은 자기가 갈 도크를 안다(주소가 dock database 에 있다). 도크가
로봇에 밀어넣는 구조는 로봇 API 에 인증 없는 인바운드를 여는 셈이고, Fleet 을
경유하면 Fleet 이 죽었을 때 충전을 못 하게 된다.

폴링은 도킹 시퀀스 중과 도크에 있는 동안에만 돈다 — 일하는 로봇에게는 비용이 없다.

표준 라이브러리만 쓴다. core 는 `install_requires=['setuptools']` 이고,
충전 상태를 읽자고 HTTP 라이브러리를 하나 들이지 않는다.

설계: docs/plans/2026-09-02-docking-station-design.md §"도크는 계측된다"
"""

from __future__ import annotations

import enum
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

#: 이 두 필드가 없으면 도크가 답한 것으로 치지 않는다. 빠진 값을 False 로
#: 채우면 "충전 안 됨"과 "말을 안 함"이 한 값으로 뭉개진다.
_REQUIRED = ("load_present", "charging")


class DockReachability(str, enum.Enum):
    """도크에 물어본 결과. 실패 사유를 구분하는 것이 이 enum 의 존재 이유다.

    상태머신이 "도크가 전류 없다고 답했다"와 "도크가 답을 안 했다"를 가르지
    못하면 재시도 전략을 세울 수 없다 — 전자는 접점 문제, 후자는 네트워크다.
    """

    OK = "ok"
    UNREACHABLE = "unreachable"      # 주소 없음, 연결 거부, DNS 실패
    TIMEOUT = "timeout"              # 응답이 제때 오지 않음
    BAD_RESPONSE = "bad_response"    # 200이 아니거나, JSON 이 아니거나, 필드 누락


@dataclass(frozen=True)
class DockStatus:
    """도크 1회 폴링 결과. 어떤 실패도 예외가 아니라 이 값으로 나온다."""

    reachability: DockReachability
    load_present: bool = False
    charging: bool = False
    current_a: Optional[float] = None
    output_voltage_v: Optional[float] = None
    output_enabled: Optional[bool] = None
    faults: tuple[str, ...] = ()
    dock_id: Optional[str] = None
    firmware: Optional[str] = None
    error: Optional[str] = None

    @property
    def answered(self) -> bool:
        return self.reachability is DockReachability.OK


def _failure(reachability: DockReachability, error: str) -> DockStatus:
    # 모를 때는 충전 중이 아니다. 기본값이 안전한 방향을 가리켜야 한다.
    return DockStatus(reachability=reachability, error=error)


class DockAgent:
    """도크의 `/status` 엔드포인트를 읽는다."""

    def __init__(self, base_url: Optional[str], timeout_s: float = 1.0,
                 path: str = "/status") -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._timeout_s = float(timeout_s)
        self._path = path

    @property
    def configured(self) -> bool:
        return self._base_url is not None

    def poll(self) -> DockStatus:
        """도크에 한 번 묻는다. 절대 예외를 올리지 않고 절대 timeout 보다 오래
        막지 않는다 — 이 호출은 틱 안에서 돌고, 멎은 도크가 틱을 멈춰 세우면
        안 된다.
        """
        if self._base_url is None:
            return _failure(DockReachability.UNREACHABLE, "no agent url configured")

        url = f"{self._base_url}{self._path}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout_s) as response:
                if response.status != 200:
                    return _failure(DockReachability.BAD_RESPONSE,
                                    f"http {response.status}")
                raw = response.read()
        except socket.timeout as error:
            return _failure(DockReachability.TIMEOUT, str(error) or "timed out")
        except urllib.error.HTTPError as error:
            return _failure(DockReachability.BAD_RESPONSE, f"http {error.code}")
        except urllib.error.URLError as error:
            # URLError 는 연결 거부도 읽기 타임아웃도 감싼다. 안쪽을 봐야
            # 네트워크 문제와 느린 도크를 구분할 수 있다.
            if isinstance(error.reason, socket.timeout):
                return _failure(DockReachability.TIMEOUT, "timed out")
            return _failure(DockReachability.UNREACHABLE, str(error.reason))
        except OSError as error:
            return _failure(DockReachability.UNREACHABLE, str(error))

        return self._parse(raw)

    def _parse(self, raw: bytes) -> DockStatus:
        try:
            document: Any = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            return _failure(DockReachability.BAD_RESPONSE, f"unparseable: {error}")

        if not isinstance(document, dict):
            return _failure(DockReachability.BAD_RESPONSE, "body is not an object")

        missing = [key for key in _REQUIRED if key not in document]
        if missing:
            return _failure(DockReachability.BAD_RESPONSE,
                            f"missing field(s): {', '.join(missing)}")

        faults = document.get("faults") or []
        if not isinstance(faults, list):
            return _failure(DockReachability.BAD_RESPONSE, "faults is not a list")

        return DockStatus(
            reachability=DockReachability.OK,
            load_present=bool(document["load_present"]),
            charging=bool(document["charging"]),
            current_a=_optional_float(document.get("current_a")),
            output_voltage_v=_optional_float(document.get("output_voltage_v")),
            output_enabled=_optional_bool(document.get("output_enabled")),
            faults=tuple(str(fault) for fault in faults),
            dock_id=_optional_str(document.get("dock_id")),
            firmware=_optional_str(document.get("firmware")),
        )


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> Optional[bool]:
    return None if value is None else bool(value)


def _optional_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)
