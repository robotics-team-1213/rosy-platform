"""D-422: the line-follow obstacle stop is measured from the URDF body along the intended path.

Pinky Pro URDF nominal (geometry.yaml, D-397): LiDAR x -0.017, body front x 0.04205 (screen
mount), rear -0.076, half width 0.05655, rotation radius 0.08257, ultrasonic x 0.0267. The
8kcn run of 2026-10-02 held at a real object 0.10-0.13 m from the LiDAR with
obstacle_stop_m 0.12 / resume 0.17, path mode, cruise 0.04 m/s.
"""

import math
from pathlib import Path

import pytest
import yaml

from core.services import _line_follow_config
from core_common.config import _deep_merge
from core_features.line_follow.clearance import body_path_gap, rotation_gap, ultrasonic_points
from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)

REPO = Path(__file__).resolve().parents[4]
PINKY = dict(body_lidar_x_m=-0.017, body_rear_x_m=-0.076, body_rotation_radius_m=0.08257,
             body_half_width_m=0.05655, body_front_x_m=0.04205, body_ultrasonic_x_m=0.0267)
LIDAR_TO_FRONT = 0.04205 + 0.017
BODY = dict(front_x_m=0.04205, rear_x_m=-0.076, half_width_m=0.05655,
            rotation_radius_m=0.08257, horizon_m=0.30)
T = 10.0


class _Events:
    def __init__(self):
        self.published = []

    def publish(self, name, **kwargs):
        self.published.append((name, kwargs))


def _manager(*, body=True, **overrides):
    config = dict(obstacle_mode="path", cruise_speed=0.04, obstacle_path_horizon_m=0.30,
                  obstacle_corridor_half_width_m=0.072, obstacle_release_s=0.0)
    config.update(PINKY if body else {})
    config.update(overrides)
    m = LineFollowManager(_Events(), config=LineFollowConfig(**config), clock=lambda: T)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    return m


def _wall(lidar_x, y_from=-0.30, y_to=0.30):
    """A wall across the robot's path, lidar_x ahead of the LiDAR (LiDAR frame points)."""
    count = int(round((y_to - y_from) / 0.005))
    return [(lidar_x, y_from + i * 0.005) for i in range(count + 1)]


def _step(m, points, *, error=0.0, confidence=1.0, t=T, range_min=0.05):
    m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True,
                              error=error, confidence=confidence), received_at=t, source_now=t)
    m.observe_body_points(points, range_min=range_min, received_at=t)
    m.observe_scan_points(points, received_at=t)
    decision = m.tick(t)
    return decision, m.status()


# ---- derived numbers --------------------------------------------------------------------

def test_stop_gap_is_margin_plus_reaction_plus_braking():
    c = LineFollowConfig(**PINKY)
    assert c.derived_stop_gap_m(0.0) == pytest.approx(0.02)
    assert c.derived_stop_gap_m(0.04) == pytest.approx(0.02 + 0.04 * 0.15 + 0.04 ** 2 / 1.0)
    assert c.derived_stop_gap_m(0.04) == pytest.approx(0.0276)
    assert c.derived_stop_gap_m(0.10) == pytest.approx(0.045)
    speeds = [0.0, 0.02, 0.04, 0.08, 0.10]
    gaps = [c.derived_stop_gap_m(v) for v in speeds]
    assert gaps == sorted(gaps) and len(set(gaps)) == len(gaps)


def test_status_reports_the_stop_gap_of_the_intended_speed():
    for cruise in (0.04, 0.08):
        m = _manager(cruise_speed=cruise)
        _, status = _step(m, _wall(0.30))
        assert status.stop_gap_m == pytest.approx(LineFollowConfig(**PINKY).derived_stop_gap_m(cruise),
                                                  abs=1e-4)


# ---- geometry ---------------------------------------------------------------------------

def test_straight_gap_is_measured_from_the_body_front_not_the_lidar():
    base = [(x - 0.017, y) for x, y in _wall(0.12)]
    assert body_path_gap(base, linear=0.04, angular=0.0, **BODY) == pytest.approx(
        0.12 - LIDAR_TO_FRONT, abs=1e-4)
    beside = [(0.10, y) for y in (-0.20, -0.07, 0.07, 0.20)]     # outside the body width
    assert body_path_gap(beside, linear=0.04, angular=0.0, **BODY) is None


def test_rotation_gap_is_outside_the_urdf_rotation_radius():
    points = [(-0.07, 0.07)]                                      # behind-left of the body
    assert rotation_gap(points, rotation_radius_m=0.08257, reach_m=0.3) == pytest.approx(
        math.hypot(0.07, 0.07) - 0.08257)


def test_ultrasonic_cone_points_sit_on_the_echo_arc():
    points = ultrasonic_points(0.10, sensor_x_m=0.0267, half_angle_deg=15.0)
    assert all(math.hypot(x - 0.0267, y) == pytest.approx(0.10) for x, y in points)
    assert min(y for _, y in points) == pytest.approx(-0.10 * math.sin(math.radians(15)))


# ---- the 8kcn corner --------------------------------------------------------------------

def _l_corner():
    """Lane end: a wall 0.13 m ahead of the LiDAR and the right-hand wall 0.11 m to the side."""
    right = [(-0.15 + i * 0.005, -0.11) for i in range(57)]
    return _wall(0.13, y_from=-0.11) + right


def test_corner_in_place_turn_was_held_by_the_lidar_origin_rule():
    """Old rule: in place, anything within obstacle_stop_m of the LiDAR is distance 0."""
    old = _manager(body=False, obstacle_stop_m=0.12, obstacle_resume_m=0.17)
    _, status = _step(old, _l_corner(), error=-0.5, confidence=0.35)   # linear 0, turn left
    assert (status.state, status.reason) == ("HOLD", "obstacle_ahead")


def test_corner_in_place_turn_is_allowed_with_the_rotation_radius():
    m = _manager(obstacle_stop_m=0.12, obstacle_resume_m=0.17)          # 8kcn overlay values
    decision, status = _step(m, _l_corner(), error=-0.5, confidence=0.35)
    assert status.state == "TRACKING" and decision.angular > 0.0 and decision.linear == 0.0
    assert status.body_gap_m == pytest.approx(0.11 - 0.08257, abs=1e-3)   # side wall, base origin
    assert status.stop_gap_m == pytest.approx(0.02)


def test_in_place_turn_still_stops_when_the_sweep_would_touch():
    m = _manager()
    _, status = _step(m, _wall(0.10), error=-0.5, confidence=0.35)     # 0.4 mm outside the sweep
    assert (status.state, status.reason) == ("HOLD", "obstacle_ahead")


def test_corner_wall_ahead_with_an_arc_turning_away_keeps_driving():
    m = _manager()
    decision, status = _step(m, _wall(0.12), error=-0.5)               # left arc toward the lane
    assert status.state == "TRACKING" and decision.linear > 0.0 and decision.angular > 0.0
    assert status.body_gap_m > status.stop_gap_m
    assert status.clearance_source == "lidar"


def test_object_beside_the_body_does_not_block_a_straight_lane():
    """The old 0.072 m corridor counted y = -0.065 m; the URDF half width is 0.05655 m."""
    side = [(0.11, -0.065 - i * 0.005) for i in range(30)]
    old = _manager(body=False, obstacle_stop_m=0.12, obstacle_resume_m=0.17)
    assert _step(old, side)[1].reason == "obstacle_ahead"
    assert _step(_manager(), side)[1].state == "TRACKING"


def test_same_wall_with_straight_intent_stops_at_the_derived_gap():
    m = _manager()
    stop = LineFollowConfig(**PINKY).derived_stop_gap_m(0.04)
    _, status = _step(m, _wall(stop + LIDAR_TO_FRONT + 0.003))
    assert status.state == "TRACKING"
    _, status = _step(m, _wall(stop + LIDAR_TO_FRONT - 0.003), t=T + 0.1)
    assert (status.state, status.reason) == ("HOLD", "obstacle_ahead")
    assert status.body_gap_m == pytest.approx(stop - 0.003, abs=1e-3)
    assert status.stop_gap_m == pytest.approx(stop, abs=1e-4)
    # resume needs the hysteresis on top of the stop gap
    _, status = _step(m, _wall(stop + LIDAR_TO_FRONT + 0.02), t=T + 0.2)
    assert status.reason == "obstacle_ahead"
    _, status = _step(m, _wall(stop + LIDAR_TO_FRONT + 0.035), t=T + 0.3)
    assert status.state == "TRACKING"


# ---- ultrasonic -------------------------------------------------------------------------

def test_ultrasonic_echo_stops_the_robot_when_the_lidar_sees_nothing():
    m = _manager()
    m.observe_ultrasonic(0.04, received_at=T)
    _, status = _step(m, [], range_min=0.15)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "ultrasonic")
    assert status.body_gap_m == pytest.approx(0.0267 + 0.04 * math.cos(math.radians(15)) - 0.04205,
                                              abs=1e-3)


def test_ultrasonic_can_only_stop_earlier_never_later():
    stop = LineFollowConfig(**PINKY).derived_stop_gap_m(0.04)
    near_wall = _wall(stop + LIDAR_TO_FRONT - 0.005)                   # LiDAR alone holds
    m = _manager()
    m.observe_ultrasonic(1.0, received_at=T)                             # far echo
    _, status = _step(m, near_wall)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "lidar")
    m = _manager()
    m.observe_ultrasonic(None, received_at=T)                            # no echo at all
    assert _step(m, near_wall)[1].reason == "obstacle_ahead"
    m = _manager()
    m.observe_ultrasonic(0.05, received_at=T)                            # nearer than the LiDAR
    _, status = _step(m, _wall(0.20))
    assert status.clearance_source == "ultrasonic" and status.body_gap_m < 0.20 - LIDAR_TO_FRONT


def test_stale_ultrasonic_is_ignored():
    m = _manager()
    m.observe_ultrasonic(0.04, received_at=T)
    _, status = _step(m, [], t=T + 0.5)                                  # older than 0.3 s
    assert status.state == "TRACKING" and status.clearance_source is None


def test_the_lidar_blind_zone_floor_holds_whatever_the_ultrasonic_says():
    """Review H1: range_min 0.17 -- a return nearer than that vanishes, so stop before it does.
    No echo, a far echo or the wall's own echo never lift the floor."""
    wall = _wall(0.16)                                                   # body gap 0.101
    for echo in ("unset", None, 1.0, 0.134):
        m = _manager()
        if echo != "unset":
            m.observe_ultrasonic(echo, received_at=T)
        _, status = _step(m, wall, range_min=0.17)
        assert status.reason == "obstacle_ahead", echo
        assert status.stop_gap_m == pytest.approx(0.17 - LIDAR_TO_FRONT, abs=1e-4)


# ---- returns that slip under range_min (review H1/H2/M2, Pinky range_min 0.15) ----------

RANGE_MIN = 0.15


def _visible(world, travelled):
    """LiDAR-frame returns of base-frame-at-start points after driving `travelled` straight."""
    out = []
    for wx, wy in world:
        point = (wx - travelled + 0.017, wy)
        if math.hypot(*point) >= RANGE_MIN:
            out.append(point)
    return out


def _drive_straight(m, world, *, scans, dt=0.5, speed=0.04):
    """Line follow drives straight; CORE issues `speed`; one scan every dt. Returns metres moved."""
    travelled, t = 0.0, T
    for index in range(scans):
        decision, status = _step(m, _visible(world, travelled), t=t, range_min=RANGE_MIN)
        assert status.state == "TRACKING", (index, status.reason)
        m.note_issued(speed, 0.0, t)
        t += dt
        travelled += speed * dt
    return travelled, t


def test_an_object_that_vanished_under_range_min_still_stops_the_robot():
    """No-echo ultrasonic, an off-axis post slips under range_min on the way: still a stop."""
    post = [(0.143, 0.04)]                                               # LiDAR range 0.165
    m = _manager()
    travelled, t = _drive_straight(m, post, scans=1)
    m.observe_ultrasonic(None, received_at=t)
    assert _visible(post, travelled) == []                               # gone from the scan
    _, status = _step(m, [], t=t, range_min=RANGE_MIN)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "lidar")
    assert status.body_gap_m == pytest.approx(0.143 - travelled - 0.04205, abs=2e-3)
    fresh = _manager()                                                   # the same scan, no memory
    assert _step(fresh, [], t=t, range_min=RANGE_MIN)[1].state == "TRACKING"


def test_a_curve_into_an_object_that_vanished_beside_the_robot_stops():
    """Review H2: a post beside the lane slips under range_min, then the lane bends into it."""
    post = [(0.128, 0.075)]                                              # LiDAR range 0.163
    m = _manager()
    travelled, t = _drive_straight(m, post, scans=3)
    assert _visible(post, travelled) == []
    _, status = _step(m, [], error=-0.3, t=t, range_min=RANGE_MIN)      # gentle left arc
    assert status.reason == "obstacle_ahead"
    assert _step(_manager(), [], error=-0.3, t=t, range_min=RANGE_MIN)[1].state == "TRACKING"


def test_in_place_turn_sees_a_remembered_object_inside_the_sweep_annulus():
    """Review M2: with range_min 0.15 the LiDAR never sees the R..R+0.02 annulus directly."""
    post = [(0.13, -0.068)]                                              # ends at base (0.07, -0.068)
    m = _manager()
    travelled, t = _drive_straight(m, post, scans=4, speed=0.03)
    assert _visible(post, travelled) == []
    _, status = _step(m, [], error=-0.5, confidence=0.35, t=t, range_min=RANGE_MIN)
    assert (status.reason, status.stop_gap_m) == ("obstacle_ahead", 0.02)
    assert status.body_gap_m == pytest.approx(math.hypot(0.13 - travelled, 0.068) - 0.08257, abs=2e-3)
    fresh = _manager()                                                   # no memory: unprotected
    assert _step(fresh, [], error=-0.5, confidence=0.35, t=t, range_min=RANGE_MIN)[1].state == "TRACKING"


def test_memory_expires_after_the_horizon_of_motion():
    post = [(0.143, 0.04)]
    m = _manager()
    travelled, t = _drive_straight(m, post, scans=1)
    with m._lock:
        m._odometer += 0.31                                              # moved past the horizon
    assert _step(m, [], t=t, range_min=RANGE_MIN)[1].state == "TRACKING"


def test_pinky_range_min_straight_stop_is_at_the_blind_edge():
    """Review M5: with range_min 0.15 the straight stop is where the LiDAR would lose the wall."""
    world = [(x - 0.017, y) for x, y in _wall(0.152)]                    # base frame
    m = _manager()
    _, status = _step(m, _visible(world, 0.0), range_min=RANGE_MIN)
    assert status.state == "TRACKING"
    assert status.stop_gap_m == pytest.approx(RANGE_MIN - LIDAR_TO_FRONT, abs=1e-4)
    m.note_issued(0.04, 0.0, T)
    # 0.02 m on, the wall ahead is under range_min; only returns beside the body remain.
    _, status = _step(m, _visible(world, 0.02), t=T + 0.5, range_min=RANGE_MIN)
    assert status.reason == "obstacle_ahead"
    assert status.body_gap_m == pytest.approx(0.152 - 0.02 - LIDAR_TO_FRONT, abs=2e-3)


def test_pinky_range_min_corner_turn_away_keeps_driving_when_the_wall_is_seen():
    m = _manager()
    decision, status = _step(m, _wall(0.24), error=-0.5, range_min=RANGE_MIN)
    assert status.state == "TRACKING" and decision.angular > 0.0
    assert status.body_gap_m is None or status.body_gap_m > status.stop_gap_m


def test_pinky_range_min_override_still_wins_above_the_blind_edge():
    m = _manager(obstacle_stop_m=0.20, obstacle_resume_m=0.28)
    _, status = _step(m, _wall(0.19), range_min=RANGE_MIN)
    assert status.reason == "obstacle_ahead"
    assert status.stop_gap_m == pytest.approx(0.20 - LIDAR_TO_FRONT, abs=1e-4)


# ---- what the command can still become (review M1) --------------------------------------

def test_sweep_covers_the_tighter_arc_the_traffic_gate_can_make():
    """APPROACH scales linear down to 0.15 but keeps angular: the arc is 6.7x tighter."""
    post = [(0.017, 0.07)]                                               # base (0.0, 0.07)
    loose = _manager()
    assert _step(loose, post, error=-0.3)[1].state == "TRACKING"
    tight = _manager()
    tight.bind_motion_envelope(lambda: (math.inf, math.inf, 0.15))
    _, status = _step(tight, post, error=-0.3)
    assert status.reason == "obstacle_ahead" and status.body_gap_m < status.stop_gap_m


def test_sweep_uses_the_safety_clipped_twist():
    """A nav linear limit below the lane speed shortens linear only: the clipped arc is swept."""
    post = [(0.017, 0.07)]
    m = _manager()
    m.bind_motion_envelope(lambda: (0.0322 * 0.15, math.inf, 1.0))
    assert _step(m, post, error=-0.3)[1].reason == "obstacle_ahead"


def test_an_unreadable_motion_envelope_fails_closed():
    m = _manager()

    def broken():
        raise RuntimeError("no limits")

    m.bind_motion_envelope(broken)
    assert _step(m, _wall(0.40))[1].reason == "obstacle_ahead"


# ---- precedence and old overlays --------------------------------------------------------

def test_explicit_stop_and_resume_override_the_derived_gap():
    m = _manager(obstacle_stop_m=0.12, obstacle_resume_m=0.17)
    _, status = _step(m, _wall(0.115))                                   # gap 0.056: derived would go
    assert status.reason == "obstacle_ahead"
    assert status.stop_gap_m == pytest.approx(0.12 - LIDAR_TO_FRONT, abs=1e-4)
    assert _step(_manager(), _wall(0.115))[1].state == "TRACKING"


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _merged(*overlays):
    config = _yaml(REPO / "src" / "contracts" / "foundation" / "config" / "rosy_default.yaml")
    for layer in overlays:
        config = _deep_merge(config, layer)
    return _line_follow_config(config["line_follow"])


PINKY_LAYER = _yaml(REPO / "src" / "products" / "pinky_pro" / "profile" / "config" / "core.yaml")


def test_packaged_layers_leave_the_stop_unset_and_know_the_body():
    default = _merged()
    assert default.obstacle_stop_m is None and not default.obstacle_override
    assert (default.sector_stop_m, default.sector_resume_m) == (0.20, 0.28)
    assert not default.body_stop_known
    pinky = _merged(PINKY_LAYER)
    assert pinky.body_stop_known and not pinky.obstacle_override
    assert pinky.body_front_x_m == 0.04205 and pinky.body_ultrasonic_x_m == 0.0267


def test_old_overlay_keeps_its_lidar_origin_meaning():
    old = {"line_follow": {"obstacle_mode": "path", "obstacle_stop_m": 0.12,
                           "obstacle_resume_m": 0.17}}
    config = _merged(PINKY_LAYER, old)
    assert config.obstacle_override and (config.sector_stop_m, config.sector_resume_m) == (0.12, 0.17)
    only_stop = _merged(PINKY_LAYER, {"line_follow": {"obstacle_stop_m": 0.15}})
    assert (only_stop.sector_stop_m, only_stop.sector_resume_m) == (0.15, 0.28)   # as before D-422


def test_override_pair_is_still_validated():
    with pytest.raises(ValueError):
        LineFollowConfig(obstacle_stop_m=0.30)                           # above the old resume 0.28
    with pytest.raises(ValueError):
        LineFollowConfig(obstacle_stop_m=float("nan"))
    with pytest.raises(ValueError):
        LineFollowConfig(**{**PINKY, "body_ultrasonic_x_m": 0.05})       # ahead of the body front


# ---- D-407 interplay --------------------------------------------------------------------

def test_stuck_front_clear_follows_the_body_decision():
    m = _manager()
    _step(m, _wall(0.16), error=-0.5)                                    # left arc, gap past resume
    with m._lock:
        inp = m._stuck_input(T)
    assert inp.front_clear is True and inp.front_band_m == pytest.approx(0.16)   # band < 0.28
    stop = LineFollowConfig(**PINKY).derived_stop_gap_m(0.04)
    _step(m, _wall(stop + LIDAR_TO_FRONT - 0.003), t=T + 0.1)
    with m._lock:
        inp = m._stuck_input(T + 0.1)
    assert inp.front_clear is False
    assert inp.front_stop_m == pytest.approx(stop + LIDAR_TO_FRONT, abs=1e-3)


def test_obstacle_hold_event_carries_the_body_gap():
    m = _manager(obstacle_escalate_s=0.5)
    wall = _wall(0.08)
    _step(m, wall)
    _step(m, wall, t=T + 0.6)
    events = [kw["data"] for name, kw in m._events.published if name == "nav.line_obstacle_hold"]
    assert events and events[0]["clearance_source"] == "lidar"
    assert events[0]["body_gap_m"] == pytest.approx(0.08 - LIDAR_TO_FRONT, abs=1e-3)
    assert events[0]["stop_gap_m"] == pytest.approx(0.0276, abs=1e-4)


def test_a_short_half_turn_still_sweeps_at_least_the_resume_gap():
    """Review M3: v 0.008, w 1.5 -> half a turn is 0.017 m; a contact just after it counts."""
    side = [(0.0, 0.08)]
    assert body_path_gap(side, linear=0.008, angular=1.5, **BODY) is None
    gap = body_path_gap(side, linear=0.008, angular=1.5, min_travel_m=0.06, **BODY)
    assert gap is not None and gap == pytest.approx(0.0199, abs=1e-3)


def test_straight_sweep_is_solved_exactly():
    """Review M4: the straight case needs no stepping; the rounded nose decides off-centre."""
    y = 0.05
    nose = min(0.04205, math.sqrt(0.08257 ** 2 - y * y))
    assert body_path_gap([(0.20, y)], linear=0.04, angular=0.0, **BODY) == pytest.approx(0.20 - nose)
    assert body_path_gap([(0.0, 0.0)], linear=0.04, angular=0.0, **BODY) == 0.0
    assert body_path_gap([(-0.20, 0.0)], linear=0.04, angular=0.0, **BODY) is None


def test_core_binds_the_envelope_from_the_safety_limits_and_the_traffic_gate():
    from types import SimpleNamespace

    from core.line_follow_wiring import bind_motion_envelope
    from core_features.traffic_policy import TrafficPolicyMode

    traffic = SimpleNamespace(mode=TrafficPolicyMode.DISABLED,
                              configuration=lambda: {"active": {"proceed_speed_scale": 0.5}})
    safety = SimpleNamespace(limits=SimpleNamespace(max_linear=0.2, max_angular=0.8))
    m = _manager()
    bind_motion_envelope(m, safety=safety, traffic_policy=traffic)
    assert m._envelope() == (0.2, 0.8, 1.0)
    traffic.mode = TrafficPolicyMode.ENFORCED
    assert m._envelope() == (0.2, 0.8, 0.15)
    traffic.configuration = lambda: {"active": {"proceed_speed_scale": 0.1}}
    assert m._envelope() == (0.2, 0.8, 0.1)
