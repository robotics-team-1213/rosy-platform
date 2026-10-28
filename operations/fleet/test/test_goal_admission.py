"""목표 어드미션 판정의 특성 시험 — 키 순서·깃발·독립 리스트 동결(계획 A단계, 검토 2026-10-28).

운영자 응답과 저장 미션의 키 **삽입 순서**까지 고정한다: dict == 같은 검사는 순서를
못 보므로 list(d.items())를 비교한다. 콘솔 수준에서는 (1) 폐쇄 실패 — 국소화가 TRUSTED였던
로봇이 goal 순간 빈 상태를 돌려주면 보류되고 목표 전송이 0회여야 하고(아무 시험도 못 박지
않았다), (2) 보류는 기존 대기열 항목을 병합 없이 교체해야 한다.
"""

from __future__ import annotations

from fakes import FakeRobot, run
from fleet.server import goal_admission
from fleet.server.console import FleetConsole
from fleet.swarm.robots import RobotEndpoint

MISSION_KEYS = ["x", "y", "yaw", "blocked_by", "waiting_on", "reason"]
RESPONSE_KEYS = ["accepted", "queued", "dispatch_attempted", "cancel_confirmed",
                 "blocked_by", "waiting_on", "reason"]


def test_pre_send_holds_carry_neither_route_nor_dispatch_flags():
    held = goal_admission.yield_hold({"for": "rosy_02"})
    untrusted = goal_admission.untrusted_self_hold("rosy_01")
    for decision in (held, untrusted):
        assert decision.route is None
        assert decision.dispatch_attempted is False
        assert decision.cancel_confirmed is False
    assert goal_admission.yield_hold(None) is None


def test_post_send_holds_carry_route_and_both_flags_true():
    conflict = goal_admission.route_conflict_hold("rosy_02", [(0.0, 0.0), (1.0, 0.0)])
    blocker = goal_admission.untrusted_blocker_hold("rosy_03", [(0.0, 0.0)])
    standing = goal_admission.standing_hold("rosy_02", ["rosy_02", "rosy_03"],
                                            "YIELDING", [(0.0, 0.0)])
    for decision in (conflict, blocker, standing):
        assert decision.route is not None
        assert decision.dispatch_attempted is True
        assert decision.cancel_confirmed is True
    # reason으로 깃발을 유도하지 않는다: LOCALIZATION_UNTRUSTED는 양 단계에 존재한다.
    assert blocker.reason == goal_admission.untrusted_self_hold("rosy_01").reason
    assert blocker.dispatch_attempted != goal_admission.untrusted_self_hold(
        "rosy_01").dispatch_attempted


def test_mission_key_order_is_frozen_and_zero_attempt_seq_survives():
    decision = goal_admission.yield_hold({"for": "rosy_02"})
    mission = goal_admission.mission_of(
        decision, 1.0, 2.0, 0.5, task_id=None, attempt_id="attempt-1", attempt_seq=0)
    assert list(mission.items()) == [
        ("x", 1.0), ("y", 2.0), ("yaw", 0.5),
        ("blocked_by", "rosy_02"), ("waiting_on", ["rosy_02"]), ("reason", "YIELDED"),
        ("attempt_id", "attempt-1"), ("attempt_seq", 0),  # 0은 None이 아니므로 남는다
    ]
    routed = goal_admission.mission_of(
        goal_admission.route_conflict_hold("rosy_02", [(0.0, 0.0)]),
        1.0, 2.0, 0.5, task_id="task-1", attempt_id=None, attempt_seq=None)
    assert list(routed.items()) == [
        ("x", 1.0), ("y", 2.0), ("yaw", 0.5),
        ("blocked_by", "rosy_02"), ("waiting_on", ["rosy_02"]), ("reason", "ROUTE_CONFLICT"),
        ("route", [(0.0, 0.0)]), ("task_id", "task-1"),
    ]


def test_response_key_order_is_frozen_and_lists_are_independent_of_the_mission():
    decision = goal_admission.untrusted_blocker_hold("rosy_03", [(0.0, 0.0)])
    response = goal_admission.response_of(decision)
    assert list(response.items()) == [
        ("accepted", False), ("queued", True), ("dispatch_attempted", True),
        ("cancel_confirmed", True), ("blocked_by", "rosy_03"),
        ("waiting_on", ["rosy_03"]), ("reason", "LOCALIZATION_UNTRUSTED"),
    ]
    mission = goal_admission.mission_of(
        decision, 1.0, 2.0, 0.5, task_id=None, attempt_id=None, attempt_seq=None)
    response["waiting_on"].append("rosy_99")
    mission["waiting_on"].append("rosy_98")
    assert response["waiting_on"] == ["rosy_03", "rosy_99"]  # 서로 독립된 가변 리스트
    assert mission["waiting_on"] == ["rosy_03", "rosy_98"]


def _console(*robots: FakeRobot) -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots))


def _localized(robot_id):
    return {"robot_id": robot_id, "navigation": "IDLE",
            "localization": {"state": "LOCALIZED", "pose_frame": "map"}}


def test_a_goal_time_empty_state_read_fails_closed():
    """TRUSTED였던 로봇이 goal 순간 빈 상태를 돌려주면 폐쇄 실패 — 보류, 전송 0회(검토 2026-10-28)."""
    robot = FakeRobot("rosy_01", state=_localized("rosy_01"))
    console = _console(robot)
    run(console.snapshot())  # 마지막 스냅샷은 LOCALIZED로 기억된다

    robot._state = {}  # goal 순간 상태 읽기가 비면 _remember는 비우고 classify(None)은 UNTRUSTED
    result = run(console.goal("rosy_01", 1.0, 2.0))

    assert result["reason"] == "LOCALIZATION_UNTRUSTED"
    assert result["dispatch_attempted"] is False
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]
    assert console._queued["rosy_01"]["reason"] == "LOCALIZATION_UNTRUSTED"


def test_a_hold_replaces_the_queued_entry_without_merging():
    """비켜서는 중인 로봇에 새 목표 — 새 YIELDED 미션이 저장 항목을 그대로 교체한다(병합 없음)."""
    robot = FakeRobot("rosy_01", state=_localized("rosy_01"))
    console = _console(robot)
    console._queued["rosy_01"] = {"x": 9.0, "y": 9.0, "yaw": 0.0, "reason": "OWN_GOAL"}
    console._yielding["rosy_01"] = {"bay": {"x": 0.0, "y": 0.0}, "for": "rosy_02"}

    result = run(console.goal("rosy_01", 1.0, 2.0))

    assert result["reason"] == "YIELDED"
    assert list(console._queued["rosy_01"].items()) == [
        ("x", 1.0), ("y", 2.0), ("yaw", 0.0),
        ("blocked_by", "rosy_02"), ("waiting_on", ["rosy_02"]), ("reason", "YIELDED"),
    ]  # 옛 OWN_GOAL 항목은 사라졌다 — 교체, not 병합
