"""D-422: the line-follow obstacle stop is measured from the URDF body along the intended path.

Pinky Pro URDF nominal (geometry.yaml, D-397): LiDAR x -0.017, body front x 0.04205 (screen
mount), rear -0.076, half width 0.05655, rotation radius 0.08257, ultrasonic x 0.0267. The
8kcn run of 2026-10-02 held at a real object 0.10-0.13 m from the LiDAR with
obstacle_stop_m 0.12 / resume 0.17, path mode, cruise 0.04 m/s.
"""

import math
import struct
from pathlib import Path

import pytest
import yaml

from core.services import _line_follow_config
from core_common.config import _deep_merge
from core_features.line_follow.clearance import (
    body_envelope_gap, body_path_gap, rotation_gap, ultrasonic_points)
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
    """Line follow drives straight; the wheels get `speed`; one scan every dt. Returns metres moved."""
    travelled, t = 0.0, T
    for index in range(scans):
        decision, status = _step(m, _visible(world, travelled), t=t, range_min=RANGE_MIN)
        assert status.state == "TRACKING", (index, status.reason)
        m.note_wheels(speed, 0.0, owned=True, now=t)
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
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")
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


# Pinky C1 range_min as the float32 the LaserScan carries (0.05000000074505806).
C1_RANGE_MIN = struct.unpack("f", struct.pack("f", 0.05))[0]


def _ring(radius, beams=640):
    return [(radius * math.cos(2 * math.pi * i / beams), radius * math.sin(2 * math.pi * i / beams))
            for i in range(beams)]


def test_a_return_at_exactly_range_min_while_stationary_is_not_remembered():
    """Gazebo 2026-10-06: returns at exactly range_min recompute a hair below it (float
    rounding) and were remembered; standing still never ages them, so HOLD forever."""
    m = _manager()
    _step(m, _ring(C1_RANGE_MIN), range_min=C1_RANGE_MIN)
    clear = _wall(0.87)
    for index in range(40):
        _, status = _step(m, clear, t=T + 0.1 * (index + 1), range_min=C1_RANGE_MIN)
    assert (status.state, status.clearance_source) == ("TRACKING", None)   # wall past horizon


def _approach_then_stand(range_min, post):
    """Drive 0.04 m at a post (LiDAR frame at the start) until it is under range_min, stand."""
    m = _manager()
    t, travelled = T, 0.0
    for _ in range(2):
        seen = [p for p in [(post[0] - travelled + 0.017, post[1])]
                if math.hypot(*p) >= range_min]
        assert seen                                                      # still visible
        _step(m, seen, t=t, range_min=range_min)
        m.note_wheels(0.04, 0.0, owned=True, now=t)
        t += 0.5
        travelled += 0.02
    assert math.hypot(post[0] - travelled + 0.017, post[1]) < range_min  # now invisible
    m.note_wheels(0.0, 0.0, owned=True, now=t)
    for index in range(40):
        _, status = _step(m, [], t=t + 0.1 * index, range_min=range_min)
    return status


def test_a_post_that_slipped_under_range_min_outside_the_body_holds_while_stationary():
    """The fix must keep D-422: a real post that went under range_min on approach stays.
    0.12 overlay: LiDAR range 0.140 -> 0.121 -> 0.102, base x 0.081 (outside the front)."""
    status = _approach_then_stand(0.12, (0.12, 0.03))
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")


def test_standing_pinky_forgets_a_vanished_point_inside_the_body_outline():
    """D-507 10: Pinky C1 range_min 0.05 < 0.0565 (LiDAR to the nearest body edge), so a point
    can only vanish inside the outline (noise or contact): no memory latch, no body_gap 0.
    C1: LiDAR range 0.070 -> 0.051 -> 0.034, base x 0.017 (inside the front 0.042)."""
    status = _approach_then_stand(C1_RANGE_MIN, (0.05, 0.02))
    assert status.state == "TRACKING"
    assert status.reason != "obstacle_ahead" and status.clearance_source != "memory"


def _remember_one(lidar_point, range_min):
    """One scan with a return already under range_min, then 40 empty scans standing still."""
    m = _manager()
    _step(m, [lidar_point], range_min=range_min)
    for index in range(40):
        _, status = _step(m, [], t=T + 0.1 * (index + 1), range_min=range_min)
    return status


def test_a_point_just_past_the_tolerance_inside_range_min_is_remembered():
    """Boundary: 2e-6 m inside range_min is inside (tolerance 1e-6 m), so it is remembered.
    0.12 overlay: the point (base x 0.103) is outside the body outline."""
    status = _remember_one((0.12 - 2e-6, 0.0), 0.12)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")


def test_a_vanished_point_just_outside_the_body_outline_is_remembered_and_stops():
    """D-507 10: 1 mm past the body front, under range_min 0.12: memory keeps it."""
    front, lidar_x = PINKY["body_front_x_m"], PINKY["body_lidar_x_m"]
    status = _remember_one((front + 0.001 - lidar_x, 0.0), 0.12)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")
    assert status.body_gap_m == pytest.approx(0.001, abs=1e-4)


def test_a_vanished_point_exactly_on_the_body_outline_is_remembered_conservative():
    """D-507 10 boundary choice: on the outline is not inside, so it is kept (and stops)."""
    half, lidar_x = PINKY["body_half_width_m"], PINKY["body_lidar_x_m"]
    point = (0.0 - lidar_x, half)                                        # base (0, half width)
    assert point[0] + lidar_x == 0.0                                     # exactly on the side
    status = _remember_one(point, 0.12)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")
    assert status.body_gap_m == 0.0


def _enter_then_move(base_point, wheels, *, range_min=0.12):
    """A return under range_min enters memory outside the body (two standing scans), then
    the wheels run each twist in `wheels` for 0.5 s, then the robot stands (10 scans)."""
    lidar_x = PINKY["body_lidar_x_m"]
    m, t = _manager(), T
    _step(m, [(base_point[0] - lidar_x, base_point[1])], t=t, range_min=range_min)
    t += 0.1
    _step(m, [], t=t, range_min=range_min)                              # remembered now
    for linear, angular in wheels:
        m.note_wheels(linear, angular, owned=True, now=t)
        t += 0.5
        _step(m, [], t=t, range_min=range_min)
    m.note_wheels(0.0, 0.0, owned=True, now=t)
    for index in range(10):
        _, status = _step(m, [], t=t + 0.1 * (index + 1), range_min=range_min)
    return status


def test_a_remembered_point_that_odometry_creeps_inside_the_body_keeps_holding():
    """D-507 10 review HIGH: the outline check is made once, when a point enters memory.
    Base x 0.083 enters outside; 0.06 m of creep puts it at 0.023, inside: contact, hold."""
    status = _enter_then_move((0.083, 0.0), [(0.04, 0.0)] * 3)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")
    assert status.body_gap_m == 0.0


def test_a_remembered_point_an_in_place_turn_rotates_into_the_body_keeps_holding():
    """Base (0.05, 0) is outside the rectangle, inside the rotation radius; a 1 rad turn
    brings it to x 0.027, inside the rectangle. It stays held."""
    status = _enter_then_move((0.05, 0.0), [(0.0, 1.0)] * 2)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")


def test_packaged_pinky_stops_with_a_zero_command_on_the_tick_a_real_box_comes_near():
    """D-507 10 must not loosen D-422: with the packaged Pinky layer (URDF body, C1 range_min)
    a box on the path, outside the body and inside the stop gap, zeroes that very tick."""
    pinky = _merged(PINKY_LAYER)
    m = LineFollowManager(_Events(), config=pinky, clock=lambda: T)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    lidar_to_front = pinky.body_front_x_m - pinky.body_lidar_x_m
    far = [(lidar_to_front + 0.20, y) for y in (-0.02, 0.0, 0.02)]
    decision, status = _step(m, far, range_min=C1_RANGE_MIN)
    assert status.state == "TRACKING" and decision.linear > 0.0
    near_gap = pinky.derived_stop_gap_m(min(pinky.cruise_speed, pinky.max_linear)) - 0.005
    box = [(lidar_to_front + near_gap, y) for y in (-0.02, 0.0, 0.02)]
    assert all(math.hypot(*p) > C1_RANGE_MIN for p in box)               # seen, not remembered
    decision, status = _step(m, box, t=T + 0.1, range_min=C1_RANGE_MIN)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "lidar")
    assert (decision.linear, decision.angular) == (0.0, 0.0)


def test_a_remembered_box_outside_the_body_zeroes_the_next_tick():
    """The box goes under range_min (0.12 overlay) outside the body: the next tick, with an
    empty scan, is a zero command from memory."""
    lidar_x = PINKY["body_lidar_x_m"]
    m = _manager()
    box = (PINKY["body_front_x_m"] + 0.03 - lidar_x, 0.0)                # LiDAR range 0.089
    decision, _ = _step(m, [box], range_min=0.12)                        # in the band, seen
    decision, status = _step(m, [], t=T + 0.1, range_min=0.12)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")
    assert (decision.linear, decision.angular) == (0.0, 0.0)


def test_returns_inside_the_body_never_enter_memory_while_moving():
    """B9 SIM bend_3..6 (2026-10-08): moving at C1 range_min, side-wall returns near range_min
    shifted under it by odometry and latched HOLD memory, body_gap 0. They are inside the
    outline, so memory stays empty on every scan, whatever the motion."""
    m = _manager()
    t = T
    for k in range(30):
        _step(m, _ring(C1_RANGE_MIN + 0.002), t=t, range_min=C1_RANGE_MIN)
        m.note_wheels(0.04, 0.4 if k % 2 else -0.4, owned=True, now=t)
        t += 0.1
        with m._lock:
            assert m._near_memory == (), k
    m.note_wheels(0.0, 0.0, owned=True, now=t)
    _, status = _step(m, _wall(0.87), t=t + 0.1, range_min=C1_RANGE_MIN)
    assert (status.state, status.clearance_source) == ("TRACKING", None)


def test_memory_outside_the_body_expires_only_after_the_horizon_of_wheel_motion():
    """A remembered point beside the body (base (0, 0.06), outside half width 0.05655) stays
    under range_min 0.12 while the robot turns in place about the base. Turning counts body
    motion at the rotation radius: kept until obstacle_path_horizon_m, forgotten after."""
    m = _manager()
    lidar_x, radius = PINKY["body_lidar_x_m"], PINKY["body_rotation_radius_m"]
    t = T
    _step(m, [(0.0 - lidar_x, 0.06)], t=t, range_min=0.12)
    _step(m, [], t=t + 0.1, range_min=0.12)
    with m._lock:
        assert len(m._near_memory) == 1
    t += 0.1
    turned = 0.0
    while True:
        m.note_wheels(0.0, 0.5, owned=True, now=t)
        t += 0.2
        turned += 0.1
        _step(m, [], t=t, range_min=0.12)
        with m._lock:
            kept = len(m._near_memory)
        if turned * radius <= 0.30 - 1e-3:
            assert kept == 1, turned
        elif turned * radius > 0.30 + 1e-3:
            break
    assert kept == 0


def test_a_lidar_whose_range_min_reaches_past_the_body_remembers_as_before():
    """D-507 10: synthetic body (front 0.10, rear -0.10, half 0.08, R 0.13, LiDAR at the base)
    and range_min 0.25. A post that vanishes outside the body still stops from memory."""
    geometry = dict(body_lidar_x_m=0.0, body_rear_x_m=-0.10, body_rotation_radius_m=0.13,
                    body_half_width_m=0.08, body_front_x_m=0.10, body_ultrasonic_x_m=None)
    m = _manager(**geometry)
    post, t = (0.26, 0.03), T
    _step(m, [post], t=t, range_min=0.25)                               # LiDAR range 0.262
    m.note_wheels(0.04, 0.0, owned=True, now=t)
    t += 0.5                                                             # 0.02 m on: range 0.242
    _, status = _step(m, [], t=t, range_min=0.25)
    assert (status.reason, status.clearance_source) == ("obstacle_ahead", "memory")
    assert status.body_gap_m == pytest.approx(0.26 - 0.02 - 0.10, abs=2e-3)
    assert _step(_manager(**geometry), [], t=t, range_min=0.25)[1].state == "TRACKING"


def test_range_min_ring_then_turn_in_place_does_not_latch_memory():
    """D-507 10 flipped the old fail-closed latch (sim2real G-07): an in-place turn moves a
    range_min ring about the base origin, not the LiDAR, so part of it lands mm inside
    range_min; with range_min 0.05 all of it is inside the body outline, so it is dropped."""
    m = _manager()
    _step(m, _ring(C1_RANGE_MIN), range_min=C1_RANGE_MIN)
    m.note_wheels(0.0, 0.5, owned=True, now=T)
    _step(m, _ring(C1_RANGE_MIN), t=T + 0.2, range_min=C1_RANGE_MIN)   # turned 0.1 rad
    m.note_wheels(0.0, 0.0, owned=True, now=T + 0.2)
    clear = _wall(0.87)
    for index in range(40):
        _, status = _step(m, clear, t=T + 0.3 + 0.1 * index, range_min=C1_RANGE_MIN)
    assert (status.state, status.clearance_source) == ("TRACKING", None)


def test_pinky_range_min_straight_stop_is_at_the_blind_edge():
    """Review M5: with range_min 0.15 the straight stop is where the LiDAR would lose the wall."""
    world = [(x - 0.017, y) for x, y in _wall(0.152)]                    # base frame
    m = _manager()
    _, status = _step(m, _visible(world, 0.0), range_min=RANGE_MIN)
    assert status.state == "TRACKING"
    assert status.stop_gap_m == pytest.approx(RANGE_MIN - LIDAR_TO_FRONT, abs=1e-4)
    m.note_wheels(0.04, 0.0, owned=True, now=T)
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
    config = _yaml(REPO / "contracts" / "foundation" / "config" / "rosy_default.yaml")
    for layer in overlays:
        config = _deep_merge(config, layer)
    return _line_follow_config(config["line_follow"])


PINKY_LAYER = _yaml(REPO / "middleware" / "apps" / "device" / "pinky" / "profile" / "config" / "core.yaml")


def test_packaged_layers_leave_the_stop_unset_and_know_the_body():
    default = _merged()
    assert default.obstacle_stop_m is None and not default.obstacle_override
    assert (default.sector_stop_m, default.sector_resume_m) == (0.20, 0.28)
    assert not default.body_stop_known
    pinky = _merged(PINKY_LAYER)
    assert pinky.body_stop_known and not pinky.obstacle_override
    assert pinky.obstacle_mode == "path"
    assert pinky.body_front_x_m == 0.04205 and pinky.body_ultrasonic_x_m == 0.0267


def test_pinky_drives_past_a_return_off_the_path_and_stops_on_the_path():
    """A sector stop holds for any return inside 0.20 m and ±20°. The packaged
    path stop holds only when the body would meet the return on the commanded path."""
    pinky = _merged(PINKY_LAYER)
    m = LineFollowManager(_Events(), config=pinky, clock=lambda: T)
    m.set_mode(LineFollowMode.CAMERA_LINE)
    # 10 cm to the side and 0.16 m from the LiDAR: inside the old 0.20 m sector
    # once the heading swings it into ±20°, and clear of the body half-width.
    assert _step(m, [(0.16, 0.10)])[1].state == "TRACKING"
    # Straight ahead, still more than 10 cm in front of the body. Sector would
    # hold (0.17 m < 0.20 m); the body gap is past the stop gap.
    ahead = 0.11 + (pinky.body_front_x_m - pinky.body_lidar_x_m)
    assert _step(m, [(ahead, 0.0)], t=T + 0.1)[1].state == "TRACKING"
    stop = pinky.derived_stop_gap_m(min(pinky.cruise_speed, pinky.max_linear))
    close = (stop - 0.01) + (pinky.body_front_x_m - pinky.body_lidar_x_m)
    held = _step(m, [(close, 0.0)], t=T + 0.2)[1]
    assert (held.state, held.reason) == ("HOLD", "obstacle_ahead")


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


@pytest.mark.parametrize("turn", [1.0, -1.0])
def test_arc_prefilter_is_mirror_symmetric(turn):
    """Review M4: the annulus/angle prefilter must not drop points on either turn side."""
    wall = [(0.10 + 0.005 * i, turn * (0.02 + 0.004 * i)) for i in range(40)]
    plain = [body_path_gap(wall[i:i + 1], linear=0.04, angular=turn * 0.3, **BODY) for i in range(40)]
    together = body_path_gap(wall, linear=0.04, angular=turn * 0.3, **BODY)
    found = [g for g in plain if g is not None]
    assert found and together == pytest.approx(min(found), abs=1e-6)
    mirrored = [(x, -y) for x, y in wall]
    assert body_path_gap(mirrored, linear=0.04, angular=-turn * 0.3, **BODY) == pytest.approx(together, abs=1e-6)


def test_tighter_arc_check_holds_for_a_right_turn_too():
    post = [(0.017, -0.07)]
    m = _manager()
    m.bind_motion_envelope(lambda: (math.inf, math.inf, 0.15))
    _, status = _step(m, post, error=0.3)
    assert status.reason == "obstacle_ahead"


# ---- re-review: odometry from the wheels, envelope sampling, prefilter wrap ---------------

def _remembering_manager():
    """A post that slipped under range_min beside the robot after one 0.02 m step."""
    m = _manager()
    travelled, t = _drive_straight(m, [(0.143, 0.04)], scans=1)
    return m, t


def test_teleop_interlude_forgets_the_memory():
    """HIGH 1: wheel output that is not line follow's own moved the robot unseen."""
    m, t = _remembering_manager()
    m.note_wheels(0.10, 0.5, owned=False, now=t)                         # teleop / docking / e-stop
    _, status = _step(m, [], t=t + 0.1, range_min=RANGE_MIN)
    assert status.state == "TRACKING"
    with m._lock:
        assert m._near_memory == () and m._odometer == 0.0


def test_a_zero_output_pause_does_not_advance_the_odometry():
    """HIGH 1: readiness HOLD / not-ready returns ZERO; the memory must not age while stopped."""
    m, t = _remembering_manager()
    with m._lock:
        before = m._odometer
    for k in range(40):                                                  # 20 s of ZERO output
        m.note_wheels(0.0, 0.0, owned=True, now=t + 0.5 * k)
        _, status = _step(m, [], t=t + 0.5 * k, range_min=RANGE_MIN)
        assert status.reason == "obstacle_ahead"
    with m._lock:
        assert m._odometer == pytest.approx(before + 0.02)               # only the drive itself


def test_odometry_integrates_the_clipped_twist_not_the_lane_command():
    m = _manager()
    _step(m, [], range_min=RANGE_MIN)
    m.note_wheels(0.015, 0.0, owned=True, now=T)                         # clipped from 0.04
    _step(m, [], t=T + 0.5, range_min=RANGE_MIN)
    with m._lock:
        assert m._odometer == pytest.approx(0.015 * 0.5)


def test_wheels_sent_owns_only_line_follow_navigation_output():
    from types import SimpleNamespace

    from core.bridge.observation import wheels_sent
    from core_features.command.arbitration import Mode

    calls = []
    line = SimpleNamespace(active=True, note_wheels=lambda l, a, owned: calls.append((l, a, owned)))
    modes = SimpleNamespace(mode=Mode.NAVIGATION, is_emergency=False)
    services = SimpleNamespace(line_follow=line, modes=modes, safety=SimpleNamespace(estop=False))
    out = SimpleNamespace(linear=0.03, angular=0.1)
    wheels_sent(services, out)
    modes.mode = Mode.MANUAL
    wheels_sent(services, out)
    modes.mode, services.safety.estop = Mode.NAVIGATION, True
    wheels_sent(services, out)
    services.safety.estop, line.active = False, False
    wheels_sent(services, out)
    assert [owned for *_, owned in calls] == [True, False, False, False]


def test_envelope_samples_the_arcs_between_the_ends():
    """HIGH 2 probe: v 0.04, w 0.2, point (0, 0.13): an in-between traffic scale hits first."""
    point = [(0.0, 0.13)]
    ends = [body_path_gap(point, linear=0.04 * s, angular=0.2, min_travel_m=0.30, **BODY)
            for s in (1.0, 0.15)]
    fine = body_envelope_gap(point, linear=0.04, angular=0.2, scale_floor=0.15, scale_step=0.002,
                             pad_m=0.0, **BODY)
    family = body_envelope_gap(point, linear=0.04, angular=0.2, scale_floor=0.15, **BODY)
    assert fine is not None and fine < 0.107                         # an in-between scale
    assert all(end is None or end > fine + 0.002 for end in ends)    # neither end sees it
    assert family is not None and fine - 0.011 <= family <= fine     # padded: early, not late


@pytest.mark.parametrize("seed", [7, 99])
def test_envelope_is_never_late_against_a_fine_scale_reference(seed):
    """Verification 2026-10-03: step 0.05 was up to 22 mm late and missed contacts near the
    resume limit. The 0.01 step + 0.01 m pad must not be late nor miss vs a 0.002 step."""
    import random

    rng = random.Random(seed)
    body = {key: value for key, value in BODY.items() if key != "horizon_m"}
    for _ in range(150):
        point = [(rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25))]
        linear, angular = rng.choice([0.02, 0.04, 0.07]), rng.uniform(-0.7, 0.7)
        want = body_envelope_gap(point, linear=linear, angular=angular, scale_floor=0.15,
                                 horizon_m=0.15, scale_step=0.002, pad_m=0.0, **body)
        got = body_envelope_gap(point, linear=linear, angular=angular, scale_floor=0.15,
                                horizon_m=0.15, **body)
        if want is not None:
            assert got is not None and got <= want + 1e-3, (point, linear, angular, got, want)
    probe = body_envelope_gap([(0.130, -0.151)], linear=0.04, angular=-0.439,
                              scale_floor=0.15, horizon_m=0.15, **body)
    assert probe is not None and probe <= 0.1475


def test_memory_hold_is_reported_as_memory_in_the_event():
    m, t = _remembering_manager()
    for k in range(12):
        m.note_wheels(0.0, 0.0, owned=True, now=t + 0.5 * k)
        _step(m, [], t=t + 0.5 * k, range_min=RANGE_MIN)
    events = [kw["data"] for name, kw in m._events.published if name == "nav.line_obstacle_hold"]
    assert events and events[0]["clearance_source"] == "memory"


def _reference_gap(points, linear, angular, horizon, min_travel=0.0, step=0.0005):
    """Unfiltered brute force: step the whole outline along the arc over every point."""
    k = angular / linear
    straight = abs(k) < 1e-9
    limit = horizon if straight else min(horizon, math.pi / abs(k))
    limit = max(limit, min_travel)
    if not straight:
        limit = min(limit, 2 * math.pi / abs(k))

    def touches(s):
        h = k * s
        px, py = (s, 0.0) if straight else (math.sin(h) / k, (1 - math.cos(h)) / k)
        c, sn = math.cos(h), math.sin(h)
        for x, y in points:
            bx, by = c * (x - px) + sn * (y - py), -sn * (x - px) + c * (y - py)
            if (-0.076 <= bx <= 0.04205 and abs(by) <= 0.05655
                    and bx * bx + by * by <= 0.08257 ** 2):
                return True
        return False

    s = 0.0
    while s <= limit + 1e-12:
        if touches(s):
            return s
        s += step
    return None


@pytest.mark.parametrize("horizon", [0.30, 2.0])
def test_prefiltered_sweep_matches_an_unfiltered_brute_force(horizon):
    """M3/M4: random points, both turn directions, short and long horizons (wrap past pi)."""
    import random

    rng = random.Random(422)
    body = {key: value for key, value in BODY.items() if key != "horizon_m"}
    for _ in range(150):
        reach = min(horizon, 0.7)
        point = [(rng.uniform(-reach, reach), rng.uniform(-reach, reach))]
        linear = rng.choice([0.01, 0.04, 0.07])
        angular = rng.choice([-1.0, 1.0]) * rng.uniform(0.05, 0.8)
        got = body_path_gap(point, linear=linear, angular=angular, horizon_m=horizon,
                            min_travel_m=0.06, **body)
        want = _reference_gap(point, linear, angular, horizon, min_travel=0.06)
        assert (got is None) == (want is None), (point, linear, angular, got, want)
        if got is not None:
            assert got == pytest.approx(want, abs=0.006), (point, linear, angular)


def test_prefilter_keeps_points_near_the_end_of_a_long_half_turn():
    """M3 probe: (-0.02, -0.54), v 0.07, w -0.256, horizon 2.0 was dropped by the angle wrap."""
    body = {key: value for key, value in BODY.items() if key != "horizon_m"}
    point = [(-0.02, -0.54)]
    got = body_path_gap(point, linear=0.07, angular=-0.256, horizon_m=2.0, **body)
    want = _reference_gap(point, 0.07, -0.256, 2.0)
    assert want is not None and got == pytest.approx(want, abs=0.006)


def test_wheels_sent_never_raises_and_holds_line_follow_until_a_fresh_scan():
    """A failure inside the 50 Hz final publisher must not stop it; the odometry is unknown,
    so the memory goes and line follow holds until its next scan."""
    from types import SimpleNamespace

    from core.bridge.observation import wheels_sent

    m, t = _remembering_manager()

    class BrokenModes:
        @property
        def mode(self):
            raise RuntimeError("modes unavailable")

    services = SimpleNamespace(line_follow=m, modes=BrokenModes(),
                               safety=SimpleNamespace(estop=False))
    problem = wheels_sent(services, SimpleNamespace(linear=0.04, angular=0.0))
    assert problem is not None and "modes unavailable" in problem
    with m._lock:
        assert m._near_memory == () and m._near_prev == ()
    decision = m.tick(t)                                                 # no new scan yet
    assert m.status().clearance_source == "odometry_lost" and decision.linear == 0.0
    _, status = _step(m, [], t=t + 0.1, range_min=RANGE_MIN)            # the next scan
    assert status.state == "TRACKING"


def test_wheels_sent_survives_a_failing_odometry_lost():
    from types import SimpleNamespace

    from core.bridge.observation import wheels_sent

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    line = SimpleNamespace(active=True, note_wheels=boom, odometry_lost=boom)
    services = SimpleNamespace(line_follow=line, modes=SimpleNamespace(mode=None, is_emergency=False),
                               safety=SimpleNamespace(estop=False))
    assert "boom" in wheels_sent(services, SimpleNamespace(linear=0.0, angular=0.0))
