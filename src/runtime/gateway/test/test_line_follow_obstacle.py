"""D-349 §11: 차선 추종 중 LiDAR 정면 물체 정지."""

import math

from core_features.line_follow.clearance import front_clearance
from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)


class _Events:
    def publish(self, *args, **kwargs):
        pass


def _scan(values_by_deg, n=360):
    """angle_min=-pi, 1 deg 간격. values_by_deg: {deg: range} 나머지는 inf."""
    ranges = [math.inf] * n
    for deg, value in values_by_deg.items():
        ranges[(deg + 180) % n] = value
    return {"ranges": ranges, "angle_min": -math.pi, "angle_max": math.pi * (n - 2) / n,
            "range_min": 0.05, "range_max": 12.0}


def test_front_sector_respects_mount_direction():
    sample = _scan({0: 0.13, 90: 0.14, 179: 2.6, -179: 2.5, -90: 1.1})
    # LiDAR 0° 가 앞이라고 보면 13 cm, 180° 장착(Pinky 실물)이면 앞은 2.5 m 다
    assert front_clearance(sample, forward_deg=0) == 0.13
    assert front_clearance(sample, forward_deg=180) == 2.5
    assert front_clearance(_scan({}), forward_deg=180) is None           # 아무것도 없음
    assert front_clearance(_scan({30: 0.1}), forward_deg=0, half_angle_deg=20) is None


def _tracking_manager(clock):
    manager = LineFollowManager(_Events(), config=LineFollowConfig(), clock=lambda: clock["t"])
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    return manager


def _see_lane(manager, t):
    manager.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                                    error=0.0, confidence=0.9), received_at=t, source_now=t)


def test_obstacle_stops_with_hysteresis_and_resumes_without_lost_latch():
    clock = {"t": 10.0}
    m = _tracking_manager(clock)
    _see_lane(m, 10.0)
    m.observe_clearance(0.50, received_at=10.0)
    assert m.tick(10.05).linear > 0

    m.observe_clearance(0.15, received_at=10.1)          # 20 cm 보다 가깝다 → 정지
    _see_lane(m, 10.1)
    held = m.tick(10.12)
    assert held.linear == 0 and m.status().reason == "obstacle_ahead"
    assert m.status().clearance_m == 0.15

    m.observe_clearance(0.24, received_at=10.2)          # 사이 값 — 아직 막힘(떨림 방지)
    _see_lane(m, 10.2)
    assert m.tick(10.22).linear == 0

    for step in range(40):                                # 오래 막혀 있어도 LOST 로 굳지 않는다
        t = 10.3 + step * 0.1
        m.observe_clearance(0.15, received_at=t)
        _see_lane(m, t)
        m.tick(t + 0.01)
    assert m.status().state == "HOLD" and m.status().reason == "obstacle_ahead"

    t = 14.5
    m.observe_clearance(0.40, received_at=t)             # 치웠다 → 곧바로 다시 간다
    _see_lane(m, t)
    assert m.tick(t + 0.01).linear > 0 and m.status().reason == "tracking"


def test_lidar_going_silent_mid_run_holds():
    clock = {"t": 10.0}
    m = _tracking_manager(clock)
    m.observe_clearance(1.0, received_at=10.0)
    _see_lane(m, 10.6)
    held = m.tick(10.61)                                  # LiDAR 마지막 값이 0.5 s 넘게 지났다
    assert held.linear == 0 and m.status().reason == "obstacle_sensor_stale"


def test_without_any_lidar_the_gate_stays_out_of_the_way():
    clock = {"t": 10.0}
    m = _tracking_manager(clock)
    _see_lane(m, 10.0)
    assert m.tick(10.05).linear > 0                        # LiDAR 없는 벤치
    assert m.status().clearance_m is None
