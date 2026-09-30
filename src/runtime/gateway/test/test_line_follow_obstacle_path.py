"""D-344 §11 보강·§13: 조향을 아는 앞 물체 정지(path)와 수동 한도 계단을 따르는 각속도 상한."""

import math
from types import SimpleNamespace

import pytest

from core.bridge import observation as bridge_observation
from core.services import _line_follow_config
from core_features.line_follow.clearance import path_clearance, scan_points
from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)


class _Events:
    def publish(self, *args, **kwargs):
        pass


def _wall_ahead(x=0.20, right_wall_y=-0.14):
    """L 모서리: 앞 x 에 가로 벽, 오른쪽에 세로 벽(로봇 좌표, y 왼쪽 +)."""
    ahead = [(x, -0.30 + i * 0.01) for i in range(61)]
    right = [(-0.10 + i * 0.01, right_wall_y) for i in range(int((x + 0.10) / 0.01))]
    return ahead + right


def _manager(**overrides):
    config = LineFollowConfig(**overrides)
    m = LineFollowManager(_Events(), config=config, clock=lambda: 10.0)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m


def _camera(m, t, error):
    m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                              error=error, confidence=0.9), received_at=t, source_now=t)


# ---- pure geometry -------------------------------------------------------------------

def test_straight_path_counts_only_the_corridor_ahead():
    points = [(0.20, 0.0), (0.10, 0.12), (-0.10, 0.0)]      # 앞 · 옆(띠 밖) · 뒤
    assert path_clearance(points, linear=0.05, angular=0.0,
                          half_width_m=0.09, horizon_m=0.4) == pytest.approx(0.20)
    assert path_clearance([(0.10, 0.12)], linear=0.05, angular=0.0,
                          half_width_m=0.09, horizon_m=0.4) is None
    assert path_clearance([(0.50, 0.0)], linear=0.05, angular=0.0,
                          half_width_m=0.09, horizon_m=0.4) is None


def test_turning_away_from_a_corner_wall_is_clear_but_driving_into_it_is_not():
    wall = _wall_ahead()
    # 왼쪽으로 크게 돈다(R ≈ 0.09 m) — 앞 0.2 m 벽은 호 둘레 띠 밖이다
    assert path_clearance(wall, linear=0.04, angular=0.48,
                          half_width_m=0.09, horizon_m=0.4) is None
    # 곧게 가면 벽이 0.2 m 앞이다
    assert path_clearance(wall, linear=0.04, angular=0.0,
                          half_width_m=0.09, horizon_m=0.4) == pytest.approx(0.20)


def test_box_on_the_arc_is_measured_along_the_arc():
    box = [(0.15, 0.05)]
    radius = 0.06 / 0.16
    arc = path_clearance(box, linear=0.06, angular=0.16, half_width_m=0.09, horizon_m=0.4)
    travel = math.atan2(0.05 - radius, 0.15) + math.pi / 2
    assert arc == pytest.approx(radius * travel)
    assert arc < 0.20


def test_in_place_rotation_counts_anything_touching_the_robot():
    assert path_clearance([(0.05, 0.05)], linear=0.0, angular=0.3,
                          half_width_m=0.09, horizon_m=0.4) == 0.0
    assert path_clearance([(0.20, 0.0)], linear=0.0, angular=0.3,
                          half_width_m=0.09, horizon_m=0.4) is None


def test_scan_points_respect_the_mount_direction():
    n = 360
    ranges = [math.inf] * n
    ranges[(180 + 180) % n] = 0.5        # LiDAR 180° — Pinky 실물의 정면
    ranges[(90 + 180) % n] = 0.3         # LiDAR +90° — 180° 장착이면 로봇 오른쪽
    sample = {"ranges": ranges, "angle_min": -math.pi, "angle_max": math.pi * (n - 2) / n,
              "range_min": 0.05, "range_max": 12.0}
    points = scan_points(sample, forward_deg=180)
    assert any(x == pytest.approx(0.5) and abs(y) < 1e-9 for x, y in points)
    assert any(abs(x) < 1e-9 and y == pytest.approx(-0.3) for x, y in points)
    assert len(scan_points(sample, forward_deg=180, max_range=0.4)) == 1


# ---- manager ------------------------------------------------------------------------

def test_corner_wall_does_not_stop_a_robot_that_is_turning_away():
    m = _manager()
    _camera(m, 10.0, error=-0.6)                    # 카메라: 왼쪽으로 크게 돌아라
    m.observe_scan_points(_wall_ahead(), received_at=10.0)
    d = m.tick(10.05)
    assert d.linear > 0 and d.angular > 0 and m.status().reason == "tracking"


def test_same_corner_stops_under_the_sector_rule_and_when_going_straight():
    sector = _manager(obstacle_mode="sector")
    _camera(sector, 10.0, error=-0.6)
    sector.observe_clearance(0.20 - 1e-3, received_at=10.0)     # 정면 부채꼴 최소 거리
    assert sector.tick(10.05).linear == 0 and sector.status().reason == "obstacle_ahead"

    straight = _manager()
    _camera(straight, 10.0, error=0.0)
    straight.observe_scan_points(_wall_ahead(x=0.15), received_at=10.0)
    assert straight.tick(10.05).linear == 0 and straight.status().reason == "obstacle_ahead"
    assert straight.status().clearance_m == pytest.approx(0.15)


def test_box_in_the_turning_path_stops_holds_with_hysteresis_and_resumes():
    m = _manager()
    _camera(m, 10.0, error=-0.2)                    # 완만한 왼쪽 회전
    m.observe_scan_points([(0.15, 0.05)], received_at=10.0)
    assert m.tick(10.05).linear == 0 and m.status().reason == "obstacle_ahead"

    # 멈춘 뒤에도 출력 0 이 아니라 의도 조향으로 잰다 — 상자는 여전히 호 위다
    for step in range(40):
        t = 10.1 + step * 0.1
        _camera(m, t, error=-0.2)
        m.observe_scan_points([(0.15, 0.05)], received_at=t)
        m.tick(t + 0.01)
    assert m.status().state == "HOLD" and m.status().reason == "obstacle_ahead"

    t = 14.2                                         # 사이 거리(0.20..0.28) — 아직 막힘
    _camera(m, t, error=0.0)
    m.observe_scan_points([(0.24, 0.0)], received_at=t)
    assert m.tick(t + 0.01).linear == 0

    t = 14.3                                         # 치웠다 → 곧바로 다시 간다
    _camera(m, t, error=0.0)
    m.observe_scan_points([(0.35, 0.0)], received_at=t)
    assert m.tick(t + 0.01).linear > 0 and m.status().reason == "tracking"


def test_path_mode_still_holds_when_the_lidar_goes_silent():
    m = _manager()
    m.observe_scan_points([], received_at=10.0)
    _camera(m, 10.6, error=0.0)
    assert m.tick(10.61).linear == 0 and m.status().reason == "obstacle_sensor_stale"


def test_without_a_usable_observation_the_last_intended_turn_is_kept():
    m = _manager()
    _camera(m, 10.0, error=-0.6)
    m.observe_scan_points(_wall_ahead(), received_at=10.0)
    assert m.tick(10.05).linear > 0
    m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=10.1, visible=False,
                              error=None, confidence=0.0), received_at=10.1, source_now=10.1)
    m.observe_scan_points(_wall_ahead(), received_at=10.1)
    m.tick(10.12)
    assert m.status().reason != "obstacle_ahead"        # 차선 문제로 서지, 벽 때문이 아니다


def test_bridge_feeds_points_in_path_mode_and_distance_in_sector_mode():
    calls = []
    sample = {"ranges": [0.15, 0.15], "angle_min": -0.01, "angle_max": 0.01,
              "range_min": 0.05, "range_max": 12.0}

    def services(mode):
        line = SimpleNamespace(
            config=LineFollowConfig(obstacle_mode=mode),
            observe_scan_points=lambda points, received_at: calls.append(("points", len(points))),
            observe_clearance=lambda distance, received_at: calls.append(("distance", distance)))
        return SimpleNamespace(line_follow=line)

    bridge_observation.front_clearance(services("path"), sample, received_at=1.0)
    bridge_observation.front_clearance(services("sector"), sample, received_at=1.0)
    assert calls == [("points", 2), ("distance", 0.15)]


def test_obstacle_config_is_validated_and_parsed():
    with pytest.raises(ValueError):
        LineFollowConfig(obstacle_mode="cone")
    with pytest.raises(ValueError):
        LineFollowConfig(obstacle_path_horizon_m=0.25)            # resume 0.28 보다 짧다
    with pytest.raises(ValueError):
        LineFollowConfig(max_angular_follows_manual="yes")
    parsed = _line_follow_config({"obstacle_mode": "sector", "obstacle_corridor_half_width_m": 0.1,
                                  "obstacle_path_horizon_m": 0.5,
                                  "max_angular_follows_manual": False})
    assert (parsed.obstacle_mode, parsed.obstacle_corridor_half_width_m,
            parsed.obstacle_path_horizon_m, parsed.max_angular_follows_manual) == (
        "sector", 0.1, 0.5, False)
    assert _line_follow_config({}).obstacle_mode == "path"


# ---- §13 angular ladder -------------------------------------------------------------

def _laddered(ceiling, **overrides):
    m = LineFollowManager(_Events(), config=LineFollowConfig(**overrides),
                          clock=lambda: 10.0, angular_ceiling=ceiling)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m


def test_angular_follows_the_manual_ladder_and_keeps_the_curvature():
    free = _laddered(None)
    _camera(free, 10.0, error=-0.8)
    wide = free.tick(10.05)
    assert wide.angular == pytest.approx(0.64)

    level0 = {"angular": 0.10}                        # D-342 L0
    m = _laddered(lambda: level0["angular"])
    _camera(m, 10.0, error=-0.8)
    d = m.tick(10.05)
    assert d.angular == pytest.approx(0.10)
    assert d.linear / d.angular == pytest.approx(wide.linear / wide.angular)   # 같은 호

    level0["angular"] = 0.30                           # 관리자가 L1 로 올렸다 — 바로 따른다
    _camera(m, 10.1, error=-0.8)
    assert m.tick(10.15).angular == pytest.approx(0.30)

    _camera(m, 10.2, error=-0.1)                        # 상한 밑이면 그대로
    small = m.tick(10.25)
    assert small.angular == pytest.approx(0.08) and small.linear > 0


def test_explicit_override_ignores_the_ladder():
    m = _laddered(lambda: 0.10, max_angular_follows_manual=False)
    _camera(m, 10.0, error=-0.8)
    assert m.tick(10.05).angular == pytest.approx(0.64)


@pytest.mark.parametrize("ceiling", [lambda: 0.0, lambda: float("nan"), lambda: 1 / 0])
def test_unusable_ladder_holds_instead_of_driving_without_steering(ceiling):
    m = _laddered(ceiling)
    _camera(m, 10.0, error=0.0)
    d = m.tick(10.05)
    assert d.linear == 0 and m.status().reason == "angular_limit_zero"


def test_ir_guard_turn_is_also_capped_by_the_ladder():
    rev = "a" * 64
    m = _laddered(lambda: 0.10, ir_guard_enabled=True, ir_calibration_revision=rev)
    _camera(m, 10.0, error=0.0)
    m.observe(LineObservation(source=LineFollowMode.IR_LINE, stamp=10.0, visible=True,
                              error=-0.8, confidence=0.9, ir_calibrated=True,
                              calibration_revision=rev), received_at=10.0, source_now=10.0)
    d = m.tick(10.05)
    assert d.angular == pytest.approx(-0.10) and m.status().reason == "lane_edge_left"
