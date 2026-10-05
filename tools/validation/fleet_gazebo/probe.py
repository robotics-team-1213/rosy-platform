"""D-426 Task 2 — 통신·결과 상관 탐침(ROS-free 판정기).

기록된 프로토콜 사실들(관측 목록)을 받아 판정을 내린다. fake HTTP/WS는 LOCAL만
증명한다(계획 T2 항목 2) — 이 모듈은 회차 기록에 대한 판정 규칙이고, 실제
Fleet/CORE 프로세스 사이의 관측은 ROS-SIM 회차(T6)가 만든다.

판정 어휘: PASS / FAIL / NOT_RUN / INCONCLUSIVE. timeout은 자동 실패/성공이
아니라 조회·이벤트 대조 대상으로 남는다(계획 T2 항목 3). 부작용 명령(재전송)은
여기서 내리지 않는다.

실제 wire 형태를 그대로 쓴다:
- HELLO 거부 코드: PAIRING_INVALID · PROTOCOL_UNSUPPORTED · DUPLICATE_IDENTITY ·
  IDENTITY_DRIFT (fleet/hub/hub.py)
- CORE 이벤트: nav.started · nav.completed · nav.failed · nav.canceled, correlation_id
  == Fleet attempt_id (fleet/server/task_results.py)
- Task 종단: COMPLETED · FAILED · HOLD (UNKNOWN은 종단이 아니다)
"""

from __future__ import annotations

from dataclasses import dataclass, field

VERDICTS = ("PASS", "FAIL", "NOT_RUN", "INCONCLUSIVE")

#: HELLO 단계에서 허브가 내는 거부 코드(fleet/hub/hub.py _hello).
WELCOME_REFUSAL_CODES = frozenset({
    "PAIRING_INVALID", "PROTOCOL_UNSUPPORTED", "DUPLICATE_IDENTITY", "IDENTITY_DRIFT",
})
IDENTITY_CONFLICT_CODES = frozenset({"DUPLICATE_IDENTITY", "IDENTITY_DRIFT"})
CONTRACT_MISMATCH_CODES = frozenset({"PROTOCOL_UNSUPPORTED"})

#: task_results.project_core_event 가 종단으로 다루는 상태.
TERMINAL_TASK_STATUSES = frozenset({"COMPLETED", "FAILED", "HOLD"})
#: 프로토콜에서 상관의 열쇠 — CORE correlation_id == Fleet attempt_id.
CORRELATION_FIELDS = ("attempt_id", "correlation_id")


@dataclass(frozen=True)
class Observation:
    """하나의 기록된 사실. 표시 시각(monotonic)과 원본 시각(시뮬 시계)을 분리한다."""

    kind: str                 # hello|welcome|welcome_refused|goal|goal_accepted|core_event|task
    at_monotonic: float
    robot_id: str
    fields: dict = field(default_factory=dict)
    source_clock: float | None = None   # 시뮬/ROS 시각. 모르면 None(나이 미지).


def _events(observations, kind, robot_id=None):
    return [o for o in observations
            if o.kind == kind and (robot_id is None or o.robot_id == robot_id)]


def session_verdict(observations) -> dict:
    """페어링→WELCOME 단계 판정. identity 충돌·거부·계약 불일치를 나눈다."""
    reasons: list[str] = []
    verdicts = {"welcome": "NOT_RUN", "identity": "NOT_RUN", "contract": "NOT_RUN"}
    refused = _events(observations, "welcome_refused")
    welcomed = _events(observations, "welcome")
    hellos = _events(observations, "hello")

    if refused:
        codes = sorted({o.fields.get("code", "UNKNOWN") for o in refused})
        for code in codes:
            if code in IDENTITY_CONFLICT_CODES:
                verdicts["identity"] = "FAIL"
                reasons.append(f"welcome refused: {code}")
            elif code in CONTRACT_MISMATCH_CODES:
                verdicts["contract"] = "FAIL"
                reasons.append(f"welcome refused: {code}")
            elif code in WELCOME_REFUSAL_CODES:
                verdicts["welcome"] = "FAIL"
                reasons.append(f"welcome refused: {code}")
            else:
                # 계약에 없는 거부 코드 자체가 계약 불일치 증거다.
                verdicts["contract"] = "FAIL"
                reasons.append(f"welcome refused with unknown code: {code}")
    if welcomed:
        if verdicts["welcome"] != "FAIL":
            verdicts["welcome"] = "PASS"
    elif not refused and hellos:
        verdicts["welcome"] = "INCONCLUSIVE"
        reasons.append("hello sent but no WELCOME or refusal was observed")
    if not hellos:
        for key in verdicts:
            verdicts[key] = "NOT_RUN"
        reasons.append("no hello observed")
    return {"verdicts": verdicts, "reasons": reasons}


def _attempt_key(observation: Observation) -> str | None:
    for name in CORRELATION_FIELDS:
        value = observation.fields.get(name)
        if value:
            return str(value)
    return None


def dispatch_chain_verdict(observations) -> dict:
    """REST goal → CORE 이벤트 → Fleet 종단 투영의 상관 판정 (시도별).

    규칙(계획 T2 항목 1의 실패 모음):
    - 수락 없는 완료 → FAIL
    - 다른 attempt 결과 → FAIL
    - 중복 종단(한 attempt에 종단 둘) → FAIL
    - 역순(종단 투영이 근거 CORE 이벤트보다 먼저 기록됨) → FAIL
    - 유실(CORE 이벤트는 있는데 종단 투영이 없음) → INCONCLUSIVE — 조회 대조 대상,
      자동 실패가 아니다.
    - 수락 뒤 종단 없음 → INCOMPLETE(INCONCLUSIVE) — timeout은 자동 실패가 아니다.
    """
    results: dict[str, dict] = {}
    goals = _events(observations, "goal")
    for goal in goals:
        attempt = _attempt_key(goal) or f"goal@{goal.at_monotonic}"
        results[attempt] = {"verdict": "NOT_RUN", "reasons": [], "robot_id": goal.robot_id}
    for observation in (g for g in observations
                        if g.kind in ("core_event", "task", "goal_accepted")):
        attempt = _attempt_key(observation)
        if attempt and attempt not in results:
            # 알려지지 않은 attempt — 다른 attempt 결과는 goal 단계에서 잡는다.
            results[attempt] = {"verdict": "NOT_RUN", "reasons": [], "robot_id": observation.robot_id}

    for attempt, result in results.items():
        accepted = [o for o in _events(observations, "goal_accepted")
                    if _attempt_key(o) == attempt]
        events = [o for o in _events(observations, "core_event")
                  if _attempt_key(o) == attempt]
        terminals = [o for o in _events(observations, "task")
                     if _attempt_key(o) == attempt
                     and o.fields.get("status") in TERMINAL_TASK_STATUSES]

        if not accepted and not events and not terminals:
            result["verdict"] = "NOT_RUN"
            continue
        verdict = "PASS"
        reasons: list[str] = []
        if not accepted and terminals:
            verdict = "FAIL"
            reasons.append("terminal without acceptance")
        if len(terminals) > 1:
            verdict = "FAIL"
            reasons.append(f"{len(terminals)} terminal projections for one attempt")
        if terminals and events:
            first_terminal = min(o.at_monotonic for o in terminals)
            justification = [o for o in events
                             if o.fields.get("event_type", "").startswith("nav.")
                             and o.fields.get("event_type") != "nav.started"]
            if justification and first_terminal < min(o.at_monotonic for o in justification):
                verdict = "FAIL"
                reasons.append("terminal projection precedes its CORE evidence")
        if not terminals and events:
            verdict = "INCONCLUSIVE"
            reasons.append("CORE events observed but no terminal projection (query, do not resend)")
        if not terminals and accepted and not events:
            verdict = "INCONCLUSIVE"
            reasons.append("accepted with no terminal and no CORE event (timeout is a comparison subject)")
        result["verdict"] = verdict
        result["reasons"] = reasons
    return results


def source_age_seconds(observation: Observation, now_monotonic: float,
                       clock_samples: list[tuple[float, float]]) -> float | None:
    """원본 나이(초). 시계 변환이 불가능하면 None — 미지이지 신선함이 아니다.

    ``clock_samples`` 는 (monotonic, source_clock) 표본. 원본 시각은 두 표본
    사이의 선형 보간으로 변환하고, 표본 밖이거나 아예 없으면 None.
    """
    if observation.source_clock is None:
        return None
    samples = sorted(clock_samples)
    if len(samples) < 2:
        return None
    (m0, s0), (m1, s1) = samples[0], samples[-1]
    span = m1 - m0
    if span <= 0:
        return None
    frac = (observation.at_monotonic - m0) / span
    if not 0.0 <= frac <= 1.0:
        return None
    converted = s0 + frac * (s1 - s0)
    age = converted - observation.source_clock
    return age if age >= 0 else None
