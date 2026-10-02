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
    def __init__(self):
        self.published = []

    def publish(self, name, **kwargs):
        self.published.append(name)


def _wall_ahead(x=0.18, right_wall_y=-0.14):
    """L 모서리: 앞 x 에 가로 벽(정지 0.20 m 보다 가깝다), 오른쪽에 세로 벽(y 왼쪽 +)."""
    ahead = [(x, -0.30 + i * 0.01) for i in range(61)]
    right = [(-0.10 + i * 0.01, right_wall_y) for i in range(int((x + 0.10) / 0.01))]
    return ahead + right


def _manager(**overrides):
    overrides.setdefault("obstacle_mode", "path")
    m = LineFollowManager(_Events(), config=LineFollowConfig(**overrides), clock=lambda: 10.0)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m


def _camera(m, t, error):
    m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                              error=error, confidence=0.9), received_at=t, source_now=t)


# ---- pure geometry -------------------------------------------------------------------

HW = 0.09


def _clearance(points, linear, angular, **kwargs):
    kwargs.setdefault("window_m", 0.28)       # = obstacle_resume_m
    kwargs.setdefault("near_m", 0.20)         # = obstacle_stop_m
    return path_clearance(points, linear=linear, angular=angular, half_width_m=HW,
                          horizon_m=0.4, **kwargs)


def _sample(returns_by_deg, *, range_min=0.15, n=360):
    """angle_min=-pi, 1 deg 간격. C1 처럼 range_min 0.15 m 안 반환은 버려진다."""
    ranges = [math.inf] * n
    for deg, value in returns_by_deg.items():
        ranges[(deg + 180) % n] = value
    return {"ranges": ranges, "angle_min": -math.pi, "angle_max": math.pi * (n - 2) / n,
            "range_min": range_min, "range_max": 12.0}


def test_straight_path_counts_only_the_corridor_ahead():
    points = [(0.18, 0.0), (0.10, 0.12), (-0.10, 0.0)]      # 앞 · 옆(띠 밖) · 뒤
    assert _clearance(points, 0.05, 0.0) == pytest.approx(0.18)
    assert _clearance([(0.10, 0.12)], 0.05, 0.0) is None
    assert _clearance([(0.50, 0.0)], 0.05, 0.0) is None


def test_corner_wall_inside_the_stop_distance_blocks_straight_but_not_a_sharp_turn_away():
    wall = _wall_ahead()
    assert _clearance(wall, 0.04, 0.0) == pytest.approx(0.18)
    assert _clearance(wall, 0.04, 0.48) is None               # R ≈ 0.083 m, 벽은 띠 밖


def test_tight_arc_sees_a_box_past_ninety_degrees_with_a_realistic_range_min():
    box_deg = round(math.degrees(math.atan2(0.10, 0.12)))
    points = scan_points(_sample({0: 0.10, box_deg: math.hypot(0.12, 0.10)}))
    assert len(points) == 1                                   # 0.10 m 반환은 range_min 에 버려진다
    radius = 0.04 / 0.48
    # 옛 판정(90° 창, near-field 없음)은 호 위 약 100° 의 이 상자를 못 봤다
    assert _clearance(points, 0.04, 0.48, window_m=0.0, near_m=0.0) is None
    arc = _clearance(points, 0.04, 0.48, near_m=0.0)          # 창 max(90°, 0.28/R) → 180°
    assert arc is not None and radius * math.pi / 2 < arc < 0.20
    near = _clearance(points, 0.04, 0.48, window_m=0.0)       # near-field 만으로도 잡힌다
    assert near == pytest.approx(math.hypot(*points[0]))


def test_pivot_uses_the_stop_distance_because_range_min_hides_the_body_ring():
    points = scan_points(_sample({30: 0.17}))
    assert _clearance(points, 0.0, 0.3, near_m=0.0) is None   # half_width 0.09 < range_min: 빈 판정
    assert _clearance(points, 0.0, 0.3) == 0.0                 # near_m = 정지 거리로 본다
    assert _clearance(scan_points(_sample({30: 0.30})), 0.0, 0.3) is None


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

def test_same_corner_straight_stops_and_turning_away_tracks():
    straight = _manager()
    _camera(straight, 10.0, error=0.0)
    straight.observe_scan_points(_wall_ahead(), received_at=10.0)
    assert straight.tick(10.05).linear == 0 and straight.status().reason == "obstacle_ahead"
    assert straight.status().clearance_m == pytest.approx(0.18)

    turning = _manager()
    _camera(turning, 10.0, error=-0.6)                        # 카메라: 왼쪽으로 크게 돌아라
    turning.observe_scan_points(_wall_ahead(), received_at=10.0)
    d = turning.tick(10.05)
    assert d.linear > 0 and d.angular > 0 and turning.status().reason == "tracking"

    sector = _manager(obstacle_mode="sector")                 # 옛 판정은 도는 중에도 선다
    _camera(sector, 10.0, error=-0.6)
    sector.observe_clearance(0.18, received_at=10.0)
    assert sector.tick(10.05).linear == 0 and sector.status().reason == "obstacle_ahead"


def test_box_in_the_turning_path_stops_holds_and_resumes_after_the_release_dwell():
    m = _manager()
    _camera(m, 10.0, error=-0.2)                              # 완만한 왼쪽 회전
    m.observe_scan_points([(0.15, 0.05)], received_at=10.0)
    assert m.tick(10.05).linear == 0 and m.status().reason == "obstacle_ahead"

    t = 10.2                                                  # 사이 거리(0.20..0.28) — 아직 막힘
    _camera(m, t, error=0.0)
    m.observe_scan_points([(0.24, 0.0)], received_at=t)
    assert m.tick(t + 0.01).linear == 0

    t = 10.3                                                  # 치웠다 — 0.2 s 동안은 아직 막힘
    for dt, moving in ((0.0, False), (0.1, False), (0.25, True)):
        _camera(m, t + dt, error=0.0)
        m.observe_scan_points([(0.35, 0.0)], received_at=t + dt)
        assert (m.tick(t + dt + 0.01).linear > 0) is moving
    assert m.status().reason == "tracking"


def test_alternating_intent_at_a_corner_does_not_chatter_stop_and_go():
    m = _manager()
    moving = []
    for step in range(20):                                    # 10 Hz, 의도가 매 틱 바뀐다
        t = 10.0 + step * 0.1
        _camera(m, t, error=-0.6 if step % 2 == 0 else 0.0)
        m.observe_scan_points(_wall_ahead(), received_at=t)
        moving.append(m.tick(t + 0.01).linear > 0)
    assert moving[0] is True and not any(moving[1:])          # 한 번 서면 떨지 않는다


def test_wall_inside_the_turning_band_holds_without_lost_and_escalates_once():
    m = _manager()
    for step in range(70):                                    # 모서리 벽 0.15 m — R+hw 안
        t = 10.0 + step * 0.1
        _camera(m, t, error=-0.6)
        m.observe_scan_points(_wall_ahead(x=0.15), received_at=t)
        assert m.tick(t + 0.01).linear == 0
    assert m.status().state == "HOLD" and m.status().reason == "obstacle_ahead"
    assert m._events.published.count("nav.line_obstacle_hold") == 1


def test_no_observation_yet_waits_instead_of_judging_a_path():
    m = _manager()
    m.observe_scan_points(_wall_ahead(x=0.10), received_at=10.0)
    assert m.tick(10.05).linear == 0
    assert m.status().state == "WAITING" and m.status().reason != "obstacle_ahead"


def test_lost_view_keeps_the_last_intended_turn():
    def reason_after_losing_view(error):
        m = _manager()
        _camera(m, 10.0, error=error)
        m.observe_scan_points(_wall_ahead(), received_at=10.0)
        m.tick(10.05)
        m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=10.1, visible=False,
                                  error=None, confidence=0.0), received_at=10.1, source_now=10.1)
        m.observe_scan_points(_wall_ahead(), received_at=10.1)
        m.tick(10.12)
        return m.status().reason

    assert reason_after_losing_view(-0.6) == "camera_line_not_visible"   # 돌던 의도 — 벽은 호 밖
    assert reason_after_losing_view(0.0) == "obstacle_ahead"             # 직진 의도 — 벽이 앞


def test_path_mode_still_holds_when_the_lidar_goes_silent():
    m = _manager()
    m.observe_scan_points([], received_at=10.0)
    _camera(m, 10.6, error=0.0)
    assert m.tick(10.61).linear == 0 and m.status().reason == "obstacle_sensor_stale"


def test_bridge_feeds_points_in_path_mode_and_distance_in_sector_mode():
    calls = []
    sample = {"ranges": [0.15, 0.15], "angle_min": -0.01, "angle_max": 0.01,
              "range_min": 0.05, "range_max": 12.0}

    def services(mode):
        line = SimpleNamespace(
            config=LineFollowConfig(obstacle_mode=mode),
            wants_body_points=False,
            observe_body_points=lambda points, range_min, received_at: calls.append(
                ("body", len(points))),
            observe_scan_points=lambda points, received_at: calls.append(("points", len(points))),
            observe_clearance=lambda distance, received_at: calls.append(("distance", distance)))
        return SimpleNamespace(line_follow=line)

    bridge_observation.front_clearance(services("path"), sample, received_at=1.0)
    bridge_observation.front_clearance(services("sector"), sample, received_at=1.0)
    # D-407: path mode also feeds its self-masked points to the stuck body clearances;
    # sector mode builds them only while a stuck can be near (wants_body_points).
    assert calls == [("body", 2), ("points", 2), ("distance", 0.15)]


def test_obstacle_config_is_validated_and_parsed():
    for bad in ({"obstacle_mode": "cone"}, {"obstacle_path_horizon_m": 0.25},
                {"max_angular_follows_manual": "yes"}, {"obstacle_release_s": -0.1},
                {"lane_auto_min_manual_angular": -1.0}):
        with pytest.raises(ValueError):
            LineFollowConfig(**bad)
    parsed = _line_follow_config({"obstacle_mode": "path", "obstacle_corridor_half_width_m": 0.1,
                                  "obstacle_path_horizon_m": 0.5, "obstacle_release_s": 0.3,
                                  "obstacle_escalate_s": 4.0, "lane_auto_min_manual_angular": 0.6,
                                  "max_angular_follows_manual": False})
    assert (parsed.obstacle_mode, parsed.obstacle_corridor_half_width_m,
            parsed.obstacle_path_horizon_m, parsed.obstacle_release_s, parsed.obstacle_escalate_s,
            parsed.lane_auto_min_manual_angular, parsed.max_angular_follows_manual) == (
        "path", 0.1, 0.5, 0.3, 4.0, 0.6, False)
    defaults = _line_follow_config({})
    assert defaults.obstacle_mode == "sector"                 # path 는 가제보·실물 확인 뒤
    assert defaults.lane_auto_min_manual_angular == pytest.approx(0.30)


# ---- §13 angular ladder -------------------------------------------------------------

def _laddered(ceiling, **overrides):
    m = LineFollowManager(_Events(), config=LineFollowConfig(**overrides),
                          clock=lambda: 10.0, angular_ceiling=ceiling)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m


def test_lane_auto_is_refused_below_ladder_l1():
    level = {"angular": 0.10}                                 # D-342 L0
    m = _laddered(lambda: level["angular"])
    _camera(m, 10.0, error=0.0)
    assert m.tick(10.05).linear == 0 and m.status().reason == "limit_level_too_low"
    level["angular"] = 0.30                                   # 관리자가 L1 로 — 바로 간다
    _camera(m, 10.1, error=0.0)
    assert m.tick(10.15).linear > 0


def test_angular_follows_the_manual_ladder_and_keeps_the_curvature():
    free = _laddered(None)
    _camera(free, 10.0, error=-0.8)
    wide = free.tick(10.05)
    assert wide.angular == pytest.approx(0.64)

    level = {"angular": 0.30}                                 # D-342 L1
    m = _laddered(lambda: level["angular"])
    _camera(m, 10.0, error=-0.8)
    d = m.tick(10.05)
    assert d.angular == pytest.approx(0.30)
    assert d.linear / d.angular == pytest.approx(wide.linear / wide.angular)   # 같은 호

    level["angular"] = 0.60                                   # L2 — 바로 따른다
    _camera(m, 10.1, error=-0.8)
    assert m.tick(10.15).angular == pytest.approx(0.60)

    _camera(m, 10.2, error=-0.1)                              # 상한 밑이면 그대로
    small = m.tick(10.25)
    assert small.angular == pytest.approx(0.08) and small.linear > 0


def test_explicit_override_ignores_the_ladder_cap_and_the_floor_can_be_disabled():
    m = _laddered(lambda: 0.30, max_angular_follows_manual=False)
    _camera(m, 10.0, error=-0.8)
    assert m.tick(10.05).angular == pytest.approx(0.64)
    floor = _laddered(lambda: 0.10, max_angular_follows_manual=False)   # 덮어쓰기는 문턱을 못 넘는다
    _camera(floor, 10.0, error=-0.8)
    assert floor.tick(10.05).linear == 0 and floor.status().reason == "limit_level_too_low"
    low = _laddered(lambda: 0.10, lane_auto_min_manual_angular=0.0)
    _camera(low, 10.0, error=-0.8)
    assert low.tick(10.05).angular == pytest.approx(0.10)


@pytest.mark.parametrize("ceiling", [lambda: 0.0, lambda: float("nan"), lambda: 1 / 0])
def test_unusable_ladder_holds_instead_of_driving_without_steering(ceiling):
    m = _laddered(ceiling)
    _camera(m, 10.0, error=0.0)
    d = m.tick(10.05)
    assert d.linear == 0 and m.status().reason == "angular_limit_zero"


def test_ir_guard_turn_is_also_capped_by_the_ladder():
    rev = "a" * 64
    m = _laddered(lambda: 0.30, ir_guard_enabled=True, ir_calibration_revision=rev)
    _camera(m, 10.0, error=0.0)
    m.observe(LineObservation(source=LineFollowMode.IR_LINE, stamp=10.0, visible=True,
                              error=-0.8, confidence=0.9, ir_calibrated=True,
                              calibration_revision=rev), received_at=10.0, source_now=10.0)
    d = m.tick(10.05)
    assert d.angular == pytest.approx(-0.30) and m.status().reason == "lane_edge_left"


def test_a_lidar_gap_restarts_the_release_dwell():
    m = _manager()
    _camera(m, 10.0, error=0.0)
    m.observe_scan_points([(0.15, 0.0)], received_at=10.0)
    assert m.tick(10.01).linear == 0                           # 막힘

    _camera(m, 10.3, error=0.0)
    m.observe_scan_points([(0.35, 0.0)], received_at=10.3)
    assert m.tick(10.31).linear == 0                           # 풀림 지연 시작
    _camera(m, 10.9, error=0.0)
    assert m.tick(10.9).linear == 0                            # LiDAR 0.6 s 끊김 — 재지 않은 틱
    assert m.status().reason == "obstacle_sensor_stale"

    _camera(m, 10.95, error=0.0)                               # 돌아왔다 — 지연은 처음부터
    m.observe_scan_points([(0.35, 0.0)], received_at=10.95)
    assert m.tick(10.96).linear == 0
    _camera(m, 11.2, error=0.0)
    m.observe_scan_points([(0.35, 0.0)], received_at=11.2)
    assert m.tick(11.21).linear > 0


def _hold_for(m, start, seconds, points):
    for step in range(int(seconds * 10)):
        t = start + step * 0.1
        _camera(m, t, error=0.0)
        m.observe_scan_points(points, received_at=t)
        m.tick(t + 0.01)


def test_reselecting_starts_a_fresh_obstacle_session_and_a_second_stop_alerts_again():
    m = _manager()
    _hold_for(m, 10.0, 6.0, [(0.15, 0.0)])
    assert m._events.published.count("nav.line_obstacle_hold") == 1
    m.set_mode(LineFollowMode.CAMERA_LINE)                     # 운전자가 다시 골랐다
    _camera(m, 16.1, error=0.0)
    m.observe_scan_points([(0.35, 0.0)], received_at=16.1)
    assert m.tick(16.11).linear > 0                            # 새 세션: 옛 막힘·지연 없음
    _hold_for(m, 16.2, 6.0, [(0.15, 0.0)])
    assert m._events.published.count("nav.line_obstacle_hold") == 2


def test_sector_reselection_with_a_near_last_reading_stays_blocked_until_the_next_scan():
    m = _manager(obstacle_mode="sector")
    _camera(m, 10.0, error=0.0)
    m.observe_clearance(0.24, received_at=10.0)                # 정지와 재출발 사이
    m.set_mode(LineFollowMode.CAMERA_LINE)
    _camera(m, 10.05, error=0.0)
    assert m.tick(10.06).linear == 0 and m.status().reason == "obstacle_ahead"
    m.observe_clearance(0.40, received_at=10.1)
    _camera(m, 10.1, error=0.0)
    assert m.tick(10.11).linear > 0
