"""D-426 Task 2 — 통신·결과 상관 탐침 판정 계약 (host, ROS-free).

실패 시험이 먼저다(계획 공통 규칙 5). 여기가 고정하는 판정:
- WELCOME 거절·identity 충돌(DUPLICATE_IDENTITY/IDENTITY_DRIFT)·계약 불일치
  (PROTOCOL_UNSUPPORTED, 알 수 없는 거부 코드)
- 수락 없는 완료 / 다른 attempt 결과 / 유실(CORE 이벤트만)·중복·역순 종단 투영
- timeout은 자동 실패가 아니다(수락-무-종단은 INCONCLUSIVE)
- 원본 나이와 표시 나이 분리 — 시계 변환 불가면 미지(None), 신선함으로 보고하지 않는다

fake 관측 목록으로 LOCAL 판정만 증명한다. 실제 프로세스 사이 관측은 ROS-SIM
회차(T6)가 만들고, 그 회차 기록도 이 판정기를 지나야 한다.
"""

from __future__ import annotations

import sys
import pytest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[3] / "tools" / "validation" / "fleet_gazebo"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from probe import (  # noqa: E402
    Observation,
    dispatch_chain_verdict,
    session_verdict,
    source_age_seconds,
)


def hello(at=1.0, robot="rosy_01", **fields):
    return Observation("hello", at, robot, fields)


def welcome(at=2.0, robot="rosy_01"):
    return Observation("welcome", at, robot, {})


def refused(at=2.0, robot="rosy_01", code="PAIRING_INVALID"):
    return Observation("welcome_refused", at, robot, {"code": code})


def goal(at=3.0, robot="rosy_01", attempt="att-1"):
    return Observation("goal", at, robot, {"attempt_id": attempt})


def accepted(at=4.0, robot="rosy_01", attempt="att-1"):
    return Observation("goal_accepted", at, robot, {"attempt_id": attempt})


def core_event(at=5.0, robot="rosy_01", attempt="att-1", event_type="nav.completed"):
    return Observation("core_event", at, robot,
                       {"correlation_id": attempt, "event_type": event_type})


def terminal(at=6.0, robot="rosy_01", attempt="att-1", status="COMPLETED"):
    return Observation("task", at, robot, {"attempt_id": attempt, "status": status})


# ---------------------------------------------------------------- session


def test_happy_session_passes():
    result = session_verdict([hello(), welcome()])
    assert result["verdicts"] == {"welcome": "PASS", "identity": "NOT_RUN", "contract": "NOT_RUN"}
    assert result["reasons"] == []


def test_welcome_refusal_fails_with_its_code():
    result = session_verdict([hello(), refused(code="PAIRING_INVALID")])
    assert result["verdicts"]["welcome"] == "FAIL"
    assert any("PAIRING_INVALID" in reason for reason in result["reasons"])


def test_identity_conflict_and_drift_are_identity_failures():
    for code in ("DUPLICATE_IDENTITY", "IDENTITY_DRIFT"):
        result = session_verdict([hello(), refused(code=code)])
        assert result["verdicts"]["identity"] == "FAIL", code
        assert result["verdicts"]["welcome"] != "FAIL", code


def test_contract_mismatch_covers_protocol_and_unknown_codes():
    result = session_verdict([hello(), refused(code="PROTOCOL_UNSUPPORTED")])
    assert result["verdicts"]["contract"] == "FAIL"
    result = session_verdict([hello(), refused(code="SOME_FUTURE_CODE")])
    assert result["verdicts"]["contract"] == "FAIL"
    assert any("unknown code" in reason for reason in result["reasons"])


def test_hello_without_answer_is_inconclusive_and_no_hello_is_not_run():
    result = session_verdict([hello()])
    assert result["verdicts"]["welcome"] == "INCONCLUSIVE"
    result = session_verdict([])
    assert set(result["verdicts"].values()) == {"NOT_RUN"}


# ------------------------------------------------------------ dispatch chain


def test_happy_chain_correlates_one_attempt():
    verdicts = dispatch_chain_verdict(
        [goal(attempt="att-1"), accepted(attempt="att-1"),
         core_event(attempt="att-1", event_type="nav.completed"),
         terminal(attempt="att-1", status="COMPLETED")])
    assert verdicts["att-1"]["verdict"] == "PASS"


def test_terminal_without_acceptance_fails():
    verdicts = dispatch_chain_verdict(
        [goal(attempt="att-1"),
         core_event(attempt="att-1", event_type="nav.completed"),
         terminal(attempt="att-1", status="COMPLETED")])
    assert verdicts["att-1"]["verdict"] == "FAIL"
    assert any("without acceptance" in r for r in verdicts["att-1"]["reasons"])


def test_result_for_another_attempt_is_its_own_verdict_not_a_pass():
    verdicts = dispatch_chain_verdict(
        [goal(attempt="att-1"), accepted(attempt="att-1"),
         accepted(attempt="att-2"),                      # 옛 수락이 새 시도에 끼어든 형태
         core_event(attempt="att-2", event_type="nav.completed"),
         terminal(attempt="att-2", status="COMPLETED")])
    assert verdicts["att-1"]["verdict"] == "INCONCLUSIVE"
    assert verdicts["att-2"]["verdict"] == "INCONCLUSIVE"


def test_duplicate_terminals_for_one_attempt_fail():
    verdicts = dispatch_chain_verdict(
        [goal(), accepted(), core_event(),
         terminal(at=6.0, status="COMPLETED"), terminal(at=7.0, status="FAILED")])
    assert verdicts["att-1"]["verdict"] == "FAIL"
    assert any("terminal projections" in r for r in verdicts["att-1"]["reasons"])


def test_terminal_preceding_its_core_evidence_fails_as_out_of_order():
    verdicts = dispatch_chain_verdict(
        [goal(), accepted(),
         terminal(at=4.5, status="COMPLETED"),
         core_event(at=5.0, event_type="nav.completed")])
    assert verdicts["att-1"]["verdict"] == "FAIL"
    assert any("precedes" in r for r in verdicts["att-1"]["reasons"])


def test_lost_projection_and_bare_timeout_are_inconclusive_not_fail():
    lost = dispatch_chain_verdict(
        [goal(), accepted(), core_event(event_type="nav.completed")])
    assert lost["att-1"]["verdict"] == "INCONCLUSIVE"
    assert any("query, do not resend" in r for r in lost["att-1"]["reasons"])
    bare = dispatch_chain_verdict([goal(), accepted()])
    assert bare["att-1"]["verdict"] == "INCONCLUSIVE"
    assert any("timeout is a comparison subject" in r for r in bare["att-1"]["reasons"])


# ------------------------------------------------------------------- ages


def test_source_age_needs_a_clock_mapping_and_stays_unknown_without_one():
    event = Observation("core_event", 5.0, "rosy_01", {}, source_clock=10.0)
    assert source_age_seconds(event, 6.0, []) is None            # 표본 없음 → 미지
    assert source_age_seconds(event, 6.0, [(5.0, 10.0)]) is None  # 표본 하나 → 미지
    samples = [(4.0, 8.0), (6.0, 12.0)]
    age = source_age_seconds(event, 6.0, samples)                # 5.0 → 시뮬 10.0
    assert age == 2.0
    stale = Observation("core_event", 4.5, "rosy_01", {}, source_clock=8.0)
    # monotonic 4.5 는 시뮬 9.0 에 해당 — 원본 표본은 8.0 이니 사실이 1 시뮬초 묵었다.
    assert source_age_seconds(stale, 6.0, samples) == 4.0
    fresher = Observation("core_event", 6.0, "rosy_01", {}, source_clock=10.0)
    assert source_age_seconds(fresher, 6.0, samples) == 2.0      # 시뮬 시각이 2초 뒤
    outside = Observation("core_event", 9.0, "rosy_01", {}, source_clock=20.0)
    assert source_age_seconds(outside, 9.0, samples) is None     # 표본 밖 → 미지
    no_clock = Observation("core_event", 5.0, "rosy_01", {}, source_clock=None)
    assert source_age_seconds(no_clock, 6.0, samples) is None


@pytest.mark.parametrize("facts,expected", [
    ([goal(), accepted(), terminal()], "INCONCLUSIVE"),
    ([goal(), accepted(), core_event(event_type="nav.started"), terminal()], "INCONCLUSIVE"),
    ([goal(), accepted(), core_event(event_type="nav.failed"), terminal()], "FAIL"),
    ([goal(), accepted(), core_event(robot="rosy_02"), terminal()], "FAIL"),
    ([goal(), accepted(robot="rosy_02"), core_event(), terminal()], "FAIL"),
    ([goal(), accepted(), core_event(), terminal(robot="rosy_02")], "FAIL"),
    ([goal(), accepted(at=2), core_event(), terminal()], "FAIL"),
    ([goal(), accepted(at=5.5), core_event(), terminal()], "FAIL"),
    ([accepted(), core_event(), terminal()], "INCONCLUSIVE"),
    ([goal(), accepted(), core_event(event_type="nav.failed"), terminal(status="FAILED")], "PASS"),
    ([goal(), accepted(), core_event(event_type="nav.canceled"), terminal(status="HOLD")], "INCONCLUSIVE"),
    ([goal(), accepted(), core_event(at=float("nan")), terminal()], "INCONCLUSIVE"),
])
def test_chain_requires_exact_robot_request_and_terminal_evidence(facts, expected):
    assert dispatch_chain_verdict(facts)["att-1"]["verdict"] == expected


@pytest.mark.parametrize("facts", [[hello(), welcome(robot="rosy_02")], [hello(), welcome(at=.5)]])
def test_welcome_cannot_be_borrowed_from_another_robot_or_precede_hello(facts):
    assert session_verdict(facts)["verdicts"]["welcome"] == "FAIL"


def test_two_announced_robots_require_both_session_responses():
    facts = [hello(), hello(robot="rosy_02"), welcome()]
    assert session_verdict(facts)["verdicts"]["welcome"] == "INCONCLUSIVE"
    assert session_verdict(facts + [welcome(robot="rosy_02")])["verdicts"]["welcome"] == "PASS"


def test_age_uses_current_piecewise_clock_and_respects_pause():
    event = Observation("core_event", 5., "rosy_01", {}, source_clock=10.)
    samples = [(4., 8.), (5., 10.), (6., 10.), (7., 14.)]
    assert source_age_seconds(event, 5., samples) == 0.
    assert source_age_seconds(event, 6., samples) == 0.
    assert source_age_seconds(event, 6.5, samples) == 2.
    assert source_age_seconds(event, 600., samples) is None


@pytest.mark.parametrize("now,samples", [
    (4., [(4., 8.), (6., 12.)]),
    (float("nan"), [(4., 8.), (6., 12.)]),
    (6., [(4., 8.), (5., 7.), (6., 12.)]),
    (6., [(4., 8.), (4., 9.), (6., 12.)]),
    (6., [(4., float("inf")), (6., 12.)]),
    (6., [(4., "unknown"), (6., 12.)]),
    (6., [(4.,), (6., 12.)]),
])
def test_invalid_clock_mapping_never_reports_freshness(now, samples):
    event = Observation("core_event", 5., "rosy_01", {}, source_clock=10.)
    assert source_age_seconds(event, now, samples) is None
