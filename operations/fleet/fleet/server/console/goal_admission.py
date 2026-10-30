"""순수 목표 어드미션 대기열 판정과 미션/응답 모양 (계획 2026-10-28-fleet-traffic-arbitration-split A단계).

콘솔은 상태 읽기(``_seen.pop``→``_remember``→``_verdict`` 폐쇄 실패 사슬)와 전송
순서·부수효과를 소유하고, 이 모듈은 **판정 문자열만** 받아 정해진 보류를 만든다.
미션과 응답의 키 순서는 통신이 이미 쓰는 그대로 얼어 있다(특성 시험이 고정).
``dispatch_attempted``/``cancel_confirmed`` 를 reason에서 유도하지 않는다 —
``LOCALIZATION_UNTRUSTED`` 는 전송 전·후 양쪽에 존재하고 깃발이 다르다.
네트워크·시계·DB 없음(검토 2026-10-28 codex·claude).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class QueueDecision:
    """한 건의 대기열 보류. 깃발은 판정 단계가 정한 그대로다."""

    reason: str
    blocked_by: str
    waiting_on: tuple
    route: Optional[tuple] = None  # None = 키 자체가 없다(전송 전 보류)
    dispatch_attempted: bool = False
    cancel_confirmed: bool = False


def yield_hold(yielding) -> Optional[QueueDecision]:
    """전송 전: 비켜서는 중인 로봇. 여기 다른 목표를 내리면 방금 비운 통로를 다시 막는다."""
    if yielding is None:
        return None
    return QueueDecision(reason="YIELDED", blocked_by=yielding["for"],
                         waiting_on=(yielding["for"],))


def untrusted_self_hold(robot_id: str) -> QueueDecision:
    """전송 전(D-395): 국소화 안 된 로봇에 목표를 주지 않는다. LOCALIZED를 기다린다."""
    return QueueDecision(reason="LOCALIZATION_UNTRUSTED", blocked_by=robot_id,
                         waiting_on=(robot_id,))


def route_conflict_hold(blocker: str, route: Sequence) -> QueueDecision:
    """전송 후: 받아들인 목표의 경로가 선점 경로와 교차 — 취소하고 대기열에."""
    return QueueDecision(reason="ROUTE_CONFLICT", blocked_by=blocker,
                         waiting_on=(blocker,), route=tuple(route),
                         dispatch_attempted=True, cancel_confirmed=True)


def untrusted_blocker_hold(untrusted: str, intended: Sequence) -> QueueDecision:
    """전송 후(D-395 P2-2): 국소화 안 된 로봇은 넓은 장애물이다 — 비켜설 자리로 보내지 않는다."""
    return QueueDecision(reason="LOCALIZATION_UNTRUSTED", blocked_by=untrusted,
                         waiting_on=(untrusted,), route=tuple(intended),
                         dispatch_attempted=True, cancel_confirmed=True)


def standing_hold(blocked_by: str, standing: Sequence, reason: str,
                  route: Sequence) -> QueueDecision:
    """전송 후(_make_room): 길을 막은 선 로봇들이 비켜서는 동안 이동자는 세워 둔다."""
    return QueueDecision(reason=reason, blocked_by=blocked_by,
                         waiting_on=tuple(standing), route=tuple(route),
                         dispatch_attempted=True, cancel_confirmed=True)


def mission_of(decision: QueueDecision, x: float, y: float, yaw: float, *,
               task_id: Optional[str], attempt_id: Optional[str],
               attempt_seq: Optional[int]) -> dict:
    """대기열 미션. 키 순서 동결: 좌표, 상세, 선택적 id(값이 None일 때만 뺀다 — 0은 남는다)."""
    mission = {"x": x, "y": y, "yaw": yaw,
               "blocked_by": decision.blocked_by,
               "waiting_on": list(decision.waiting_on),
               "reason": decision.reason}
    if decision.route is not None:
        mission["route"] = list(decision.route)
    if task_id is not None:
        mission["task_id"] = task_id
    if attempt_id is not None:
        mission["attempt_id"] = attempt_id
    if attempt_seq is not None:
        mission["attempt_seq"] = attempt_seq
    return mission


def response_of(decision: QueueDecision) -> dict:
    """운영자 응답. 키 순서 동결, 저장 미션과는 독립된 가변 리스트."""
    return {"accepted": False, "queued": True,
            "dispatch_attempted": decision.dispatch_attempted,
            "cancel_confirmed": decision.cancel_confirmed,
            "blocked_by": decision.blocked_by,
            "waiting_on": list(decision.waiting_on),
            "reason": decision.reason}


def cancel_confirmed(receipt) -> bool:
    """로봇이 취소를 확인했는가. 확인 없이 대기열에 넣으면 목표가 살아 있는 채로 기다린다."""
    return (isinstance(receipt, dict)
            and (receipt.get("canceled") is True or receipt.get("navigation") == "CANCELED"))
