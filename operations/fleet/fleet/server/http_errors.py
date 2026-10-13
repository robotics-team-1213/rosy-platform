"""Fleet HTTP 표면의 예외 → 응답 매핑.

`app.py`가 가졌 있던 `_http_error` 다. 로봇·신호등·허브 예외를 어떤 상태 코드와
본문 모양으로 바꿀지는 표면의 계약이므로 라우트 모듈들이 함께 쓴다.
"""

from __future__ import annotations

from fastapi import HTTPException

from fleet.hub.hub import HubError
from fleet.server.signals import SignalApiError
from fleet.swarm.transport import RobotApiError


def http_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, HubError):
        # 409 는 "지금 상태에서는 안 된다"(이미 대형이 열려 있음, 팔로워가 대형에 묶임)이고,
        # 400 은 "요청이 틀렸다"(없는 대형 이름)다. 화면이 둘을 다르게 안내해야 한다.
        conflict = {"FORMATION_ACTIVE", "NO_FORMATION", "REFORM_REFUSED",
                    "RESUME_REFUSED", "ARMING_FAILED", "NO_FOLLOWERS", "TRIP_ROBOT_BUSY"}
        status = (404 if exc.code in ("UNKNOWN_ROBOT", "UNKNOWN_SIGNAL", "NO_SIGNALS")
                  else 409 if exc.code in conflict else 400)
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, SignalApiError):
        # 신호등이 거절한 것이다 — 400 conflict 같은 장치 코드를 그대로 화면에 옮긴다.
        return HTTPException(status_code=502,
                             detail={"code": exc.code, "message": str(exc),
                                     "signal_id": exc.signal_id})
    if isinstance(exc, RobotApiError):
        # 로봇이 거절한 것이지 관제가 잘못 만든 요청이 아니다 — 502 로 그 사실을 남긴다.
        return HTTPException(status_code=502,
                             detail={"code": exc.code, "message": str(exc),
                                     "robot_id": exc.robot_id})
    return HTTPException(status_code=502,
                         detail={"code": type(exc).__name__, "message": str(exc)})
