"""D-426 Task 3 — 수치 판정기 계약 (host, ROS-free). 실패 시험이 먼저다(규칙 5).

고정하는 것(계획 T3 항목 1·3·4·5):
- 성공 이벤트만 있고 이동 없음 → FAIL
- 잘못된 로봇 이동(명령받지 않은 로봇) → FAIL
- map/odom 혼용 → FAIL
- stale pose → INCONCLUSIVE(위치 단언 근거 상실, 네트워크 시한은 monotonic)
- contact: 양성 대조 미통과면 단언 금지(NOT_RUN), 접촉 있으면 FAIL
- 관측 빈 구간 >0.15 s → 충돌 계열 INCONCLUSIVE
- pause/reset → 새 epoch, 이전 물리 단언 이어붙이지 않음
- 도착 0.10 m/10°, 정지 1 s 연속, footprint 경계 여유(중심 거리 아님)
- 단언 기록은 관측원·단위·시계·임계값·원본 위치를 남긴다
- 의도적 잘못된 실행(변이)이 판정기를 FAIL시킨다
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "validation" / "fleet_gazebo"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from assertions import (  # noqa: E402
    ARRIVAL_HEADING_DEG,
    ARRIVAL_POSITION_M,
    ContactEvent,
    PoseSample,
    arrival,
    clearance,
    claimed_motion_verdict,
    contacts,
    displacement_m,
    epoch_cut,
    footprint_clearance_m,
    frame_consistency,
    observation_gaps,
    rate_verdict,
    stale_pose,
    standstill,
    wrong_robot_motion,
)
from observer import Recorder, check_publisher_ownership  # noqa: E402

#: 핑키 실측 footprint 근사(URDF 0.172 m 차체, mm 단위 근사 사각형).
FOOTPRINT = [(-0.086, -0.062), (0.086, -0.062), (0.086, 0.062), (-0.086, 0.062)]


def pose(robot="rosy_01", t=0.0, mono=0.0, x=0.0, y=0.0, yaw=0.0,
         v=0.0, w=0.0, frame="map"):
    return PoseSample(robot, t, mono, x, y, yaw, v, w, frame)


def drove(robot="rosy_01", samples=10, dt=0.05, start=(0.0, 0.0), end=(1.0, 0.0)):
    """직선 이동 관측. dt=0.05 → 20 Hz."""
    made = []
    for i in range(samples):
        frac = i / (samples - 1)
        x = start[0] + (end[0] - start[0]) * frac
        y = start[1] + (end[1] - start[1]) * frac
        made.append(pose(robot, t=i * dt, mono=i * dt, x=x, y=y))
    return made


GOAL = {"x": 1.0, "y": 0.0, "yaw": 0.0}


def test_arrival_thresholds_and_provenance():
    at_goal = drove(end=(1.0, 0.0))
    result = arrival(at_goal, robot_id="rosy_01", goal=GOAL)
    assert result["verdict"] == "PASS"
    assert result["observer"] == "gz-model-pose" and result["clock"] == "sim"
    assert result["threshold"]["position_m"] == ARRIVAL_POSITION_M
    assert result["threshold"]["heading_deg"] == ARRIVAL_HEADING_DEG
    assert result["evidence"], "every verdict names its evidence"


def test_arrival_fails_beyond_threshold():
    off = drove(end=(1.0, 0.12))   # 0.12 m > 0.10 m
    assert arrival(off, robot_id="rosy_01", goal=GOAL)["verdict"] == "FAIL"
    skewed = [pose(t=i * 0.05, mono=i * 0.05, x=1.0, yaw=math.radians(30))
              for i in range(10)]
    assert arrival(skewed, robot_id="rosy_01", goal=GOAL)["verdict"] == "FAIL"


def test_standstill_needs_a_full_quiet_second():
    quiet = [pose(t=i * 0.05, mono=i * 0.05, x=1.0, v=0.0, w=0.0) for i in range(21)]
    assert standstill(quiet, robot_id="rosy_01")["verdict"] == "PASS"
    creep = [pose(t=i * 0.05, mono=i * 0.05, x=1.0, v=0.02) for i in range(21)]
    assert standstill(creep, robot_id="rosy_01")["verdict"] == "FAIL"
    spin = [pose(t=i * 0.05, mono=i * 0.05, x=1.0, w=0.05) for i in range(21)]
    assert standstill(spin, robot_id="rosy_01")["verdict"] == "FAIL"
    short = [pose(t=i * 0.05, mono=i * 0.05, x=1.0) for i in range(5)]  # 0.2 s 만
    assert standstill(short, robot_id="rosy_01")["verdict"] == "INCONCLUSIVE"


def test_clearance_uses_footprint_boundaries_not_centers():
    # 중심 거리 0.24 m 는 footprint 반폭 합(0.124) 위로 여유가 있어 보이지만,
    # 한 대를 45° 비틀면 모서리가 접근해 경계 거리가 0.10 m 아래로 떨어진다.
    a = pose("rosy_01", t=0, x=0.0, y=0.0, yaw=0.0)
    rotated = pose("rosy_02", t=0, x=0.0, y=0.24, yaw=math.radians(45))
    gap = footprint_clearance_m(a, rotated, FOOTPRINT, FOOTPRINT)
    assert gap < 0.10, "rotation must shrink the boundary gap below the threshold"
    ok = clearance([(a, rotated)], {"rosy_01": FOOTPRINT, "rosy_02": FOOTPRINT})
    assert ok["verdict"] == "FAIL" and ok["evidence"][0]["min_gap_m"] < 0.10


def test_contacts_zero_requires_positive_control():
    robots = ("rosy_01", "rosy_02")
    no_events = []
    forbidden = contacts(no_events, robot_ids=robots, positive_control_passed=False)
    assert forbidden["verdict"] == "NOT_RUN"
    assert "forbidden" in forbidden["evidence"][0]["reason"]
    good = contacts(no_events, robot_ids=robots, positive_control_passed=True)
    assert good["verdict"] == "PASS"
    hit = [ContactEvent("rosy_01", t=1.0, mono=1.0, other="rosy_02")]
    assert contacts(hit, robot_ids=robots, positive_control_passed=True)["verdict"] == "FAIL"
    gappy = contacts(no_events, robot_ids=robots, positive_control_passed=True,
                     collision_inconclusive=True)
    assert gappy["verdict"] == "INCONCLUSIVE"


def test_observation_gap_makes_collision_inconclusive():
    steady = drove(samples=20)
    assert observation_gaps(steady, robot_id="rosy_01")["inconclusive_collision"] is False
    holed = drove(samples=5) + [                        # t=0.00..0.20
        pose(t=0.5 + i * 0.05, mono=0.5 + i * 0.05, x=0.5 + i * 0.01) for i in range(5)]
    report = observation_gaps(holed, robot_id="rosy_01")  # 0.20→0.50 빈 구간 0.30 s
    assert report["inconclusive_collision"] is True and report["evidence"]


def test_rate_verdict_pins_20hz():
    assert rate_verdict(drove(samples=21), robot_id="rosy_01")["verdict"] == "PASS"
    slow = [pose(t=i * 0.1, mono=i * 0.1, x=i * 0.01) for i in range(6)]  # 10 Hz
    assert rate_verdict(slow, robot_id="rosy_01")["verdict"] == "FAIL"


def test_success_event_without_motion_fails():
    still = [pose(t=i * 0.05, mono=i * 0.05, x=0.0) for i in range(21)]
    assert displacement_m(still, robot_id="rosy_01") == 0.0
    verdict = claimed_motion_verdict(
        displacement=displacement_m(still, robot_id="rosy_01"),
        terminal_status="COMPLETED")
    assert verdict["verdict"] == "FAIL"
    drove_samples = drove(samples=21)
    assert claimed_motion_verdict(
        displacement=displacement_m(drove_samples, robot_id="rosy_01"),
        terminal_status="COMPLETED")["verdict"] == "PASS"


def test_wrong_robot_motion_fails_and_ignores_the_commanded_one():
    both = drove("rosy_01") + drove("rosy_02")
    verdict = wrong_robot_motion(both, commanded="rosy_01")
    assert verdict["verdict"] == "FAIL" and verdict["evidence"][0]["moved"] == ["rosy_02"]
    assert wrong_robot_motion(drove("rosy_01"), commanded="rosy_01")["verdict"] == "PASS"


def test_frame_mixing_is_a_failure():
    mixed = drove(samples=10) + [pose(t=0.5, mono=0.5, x=1.0, frame="odom")]
    verdict = frame_consistency(mixed, robot_id="rosy_01")
    assert verdict["verdict"] == "FAIL"
    assert verdict["evidence"][0]["foreign_frames"] == ["odom"]


def test_stale_pose_is_inconclusive_on_the_monotonic_clock():
    fresh = drove(samples=10)
    assert stale_pose(fresh, robot_id="rosy_01", now_mono=0.5)["verdict"] == "PASS"
    assert stale_pose(fresh, robot_id="rosy_01", now_mono=5.0)["verdict"] == "INCONCLUSIVE"
    empty = stale_pose([], robot_id="rosy_01", now_mono=0.0)
    assert empty["verdict"] == "NOT_RUN" and empty["clock"] == "monotonic"


def test_pause_reset_cuts_epochs_and_does_not_stitch():
    before = drove(samples=10)                                   # 0.00–0.45 s, x 0→1
    after = [pose(t=1.0 + i * 0.05, mono=1.0 + i * 0.05, x=5.0) for i in range(10)]
    old, new = epoch_cut(before + after, pause_at_t=1.0)
    assert len(old) == 10 and len(new) == 10
    # epoch 분리로 경계 점프(x 1.0→5.0)가 이동량에 섞이지 않는다.
    assert displacement_m(old, robot_id="rosy_01") == 1.0
    assert displacement_m(new, robot_id="rosy_01") == 0.0


def test_recorder_keeps_epochs_and_gaps_per_robot():
    ticks = iter(float(i) for i in range(100))            # 진행하는 monotonic 시계
    recorder = Recorder(clock=lambda: next(ticks))
    recorder.attach_pose_source(lambda: [pose(t=i * 0.2, mono=1.0) for i in range(3)])
    recorder.poll()
    recorder.mark_epoch_end("pause")
    recorder.attach_pose_source(lambda: [pose(t=1.0, mono=50.0, x=5.0)])
    recorder.poll()
    assert [e.reason for e in recorder.epochs] == ["pause", "run-start"]
    first = recorder.epochs[0]
    assert len(recorder.poses_in(first, robot_id="rosy_01")) == 3
    assert recorder.rate_ok(first, robot_id="rosy_01") is False  # 5 Hz 미달


def test_publisher_ownership_checks_name_and_pid():
    expected = {"rosy_01/cmd_vel": {"publisher": "/rosy_01/core", "pid": 4242}}
    ok = check_publisher_ownership(
        [{"topic": "rosy_01/cmd_vel", "publisher": "/rosy_01/core", "pid": 4242}],
        expected)
    assert ok["ok"] is True
    foreign = check_publisher_ownership(
        [{"topic": "rosy_01/cmd_vel", "publisher": "/rosy_02/core", "pid": 4242}], expected)
    assert foreign["ok"] is False and any("!=" in p for p in foreign["problems"])
    stranger_pid = check_publisher_ownership(
        [{"topic": "rosy_01/cmd_vel", "publisher": "/rosy_01/core", "pid": 9999}], expected)
    assert stranger_pid["ok"] is False and any("pid" in p for p in stranger_pid["problems"])
    unexpected = check_publisher_ownership(
        [{"topic": "rosy_02/cmd_vel", "publisher": "/rosy_02/core"}], expected)
    assert unexpected["ok"] is False


def test_intentional_bad_run_fails_the_judge_mutation_style():
    """변이 증명(계획 T3 항목 5): 잘못된 실행이 판정기를 PASS로 넘기지 않는다."""
    healthy = drove(samples=21)
    # 변이 1: 목표를 관측과 어긋나게 놓으면 도착은 FAIL
    far_goal = {"x": 3.0, "y": 0.0, "yaw": 0.0}
    assert arrival(healthy, robot_id="rosy_01", goal=far_goal)["verdict"] == "FAIL"
    # 변이 2: 이동 관측을 지우면 claimed-motion FAIL
    stillborn = [pose(t=i * 0.05, mono=i * 0.05, x=0.0) for i in range(21)]
    assert claimed_motion_verdict(
        displacement=displacement_m(stillborn, robot_id="rosy_01"),
        terminal_status="COMPLETED")["verdict"] == "FAIL"
    # 변이 3: 두 로봇을 겹치게 놓으면 여유 FAIL
    overlapped = [(pose("rosy_01", t=0, x=0.0), pose("rosy_02", t=0, x=0.05))]
    assert clearance(overlapped, {"rosy_01": FOOTPRINT, "rosy_02": FOOTPRINT})["verdict"] == "FAIL"
