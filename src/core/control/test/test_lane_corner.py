"""Odometry-bounded 90 deg corner turning for two-line lane mode.

Gazebo run 164757: the lane-centre detector held the centre to 1 mm, then
stopped fail-closed at the first corner, where the inner line ends, the outer
line crosses ahead and the new lane opens to one side. Frames here are
rendered by inverse projection from a pose, through the same declared Gazebo
camera geometry, and the loop is closed with CORE's line_follow command law
so the manoeuvre is judged by where the robot actually ends up.
"""

import math

import numpy as np
import pytest

from control.sensing.camera_ground import simulation_ground_plane
from control.sensing.lane import (
    LaneCornerTracker,
    LaneObservation,
    detect_lane_corner,
)

H = 0.0925              # lane half-width
LW = 0.025              # painted line width
CAM_X = 0.034           # camera optical centre ahead of base_link
X_T = 0.60              # transverse (outer) line centre, world x
W, HT = 320, 180
FLOOR, PAINT, BODY = 109, 225, 218
DT = 0.2                # 5 Hz camera

KW = dict(bright_threshold=220, lane_half_width_m=H,
          roi_top_fraction=0.25, roi_bottom_fraction=0.75, washed_fraction=0.75)
CORNER_KW = dict(bright_threshold=220, lane_half_width_m=H)

GROUND = simulation_ground_plane(
    source="GAZEBO", simulation_enabled=True, use_sim_time=True,
    width_px=W, height_px=HT, height_m=0.060194,
    pitch_rad=math.radians(25.0), hfov_rad=1.1519, max_range_m=0.6)

# Per-pixel camera-frame floor coordinates, pose independent.
_FWD = np.full((HT, W), np.nan)
_LAT = np.full((HT, W), np.nan)
for _r in range(HT):
    _d = GROUND.distance(_r)
    if _d is None:
        continue
    _FWD[_r, :] = _d
    _LAT[_r, :] = [GROUND.lateral(_c, _r) for _c in range(W)]


def _rect(x0, x1, y0, y1):
    return (min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1))


def straight_lane():
    half = LW / 2.0
    return [_rect(-10, 10, -H - half, -H + half), _rect(-10, 10, H - half, H + half)]


def l_corner(side="LEFT"):
    """World frame, x forward along the approach, y left. The lane turns to
    `side`: the inner line on that side ends, the outer line crosses ahead."""
    s = 1.0 if side == "LEFT" else -1.0
    half = LW / 2.0
    return [
        # outer side line, continues to the transverse line
        _rect(-10, X_T + half, -s * (H - half), -s * (H + half)),
        # transverse outer line, spanning into the new lane
        _rect(X_T - half, X_T + half, -s * (H + half), s * 10),
        # inner side line, ends where the new lane's inner line starts
        _rect(-10, X_T - 2 * H + half, s * (H - half), s * (H + half)),
        # new lane's inner line
        _rect(X_T - 2 * H - half, X_T - 2 * H + half, s * (H - half), s * 10),
    ]


def render(pose, rects):
    x, y, yaw = pose
    forward = _FWD + CAM_X
    left = -_LAT
    wx = x + forward * math.cos(yaw) - left * math.sin(yaw)
    wy = y + forward * math.sin(yaw) + left * math.cos(yaw)
    painted = np.zeros((HT, W), dtype=bool)
    for x0, x1, y0, y1 in rects:
        painted |= (wx >= x0) & (wx <= x1) & (wy >= y0) & (wy <= y1)
    frame = np.full((HT, W), FLOOR, dtype=np.uint8)
    frame[painted] = PAINT
    frame[139:, :] = BODY
    return frame


def core_command(obs):
    """CORE line_follow tick(): min_confidence 0.35, cruise 0.08, gain 0.8."""
    if obs is None or obs.confidence < 0.35:
        return 0.0, 0.0
    scale = max(0.0, min(1.0, (obs.confidence - 0.35) / 0.65))
    linear = 0.08 * scale * max(0.2, 1.0 - 0.65 * abs(obs.error))
    angular = max(-0.7, min(0.7, -0.8 * obs.error))
    return linear, angular


def _step(pose, obs):
    x, y, yaw = pose
    v, w = core_command(obs)
    mid = yaw + w * DT / 2.0
    return (x + v * DT * math.cos(mid), y + v * DT * math.sin(mid), yaw + w * DT)


def drive(rects, *, steps, odom=True):
    tracker = LaneCornerTracker(camera_x_offset_m=CAM_X)
    log = []
    pose = (0.0, 0.0, 0.0)
    for k in range(steps):
        obs = tracker.update(k * DT, pose if odom else None, render(pose, rects),
                             GROUND, **KW)
        log.append((tracker.state, obs, pose))
        pose = _step(pose, obs)
    return log, tracker


def _into_turn(side="LEFT"):
    """Drive the closed loop until the tracker has just entered TURN."""
    tracker = LaneCornerTracker(camera_x_offset_m=CAM_X)
    pose, now = (0.0, 0.0, 0.0), 0.0
    for _ in range(80):
        obs = tracker.update(now, pose, render(pose, l_corner(side)), GROUND, **KW)
        if tracker.state == "TURN":
            return tracker, pose, now
        pose = _step(pose, obs)
        now += DT
    raise AssertionError("never entered TURN")


def test_straight_lane_frames_show_no_corner():
    for y in (-0.02, 0.0, 0.02):
        for yaw in (-0.1, 0.0, 0.1):
            frame = render((0.0, y, yaw), straight_lane())
            assert detect_lane_corner(frame, GROUND, **CORNER_KW) is None


def test_straight_lane_never_triggers_a_corner():
    log, _ = drive(straight_lane(), steps=60)
    assert {state for state, _, _ in log} == {"FOLLOW"}
    assert all(obs is not None and abs(obs.error) < 0.1 for _, obs, _ in log)


def test_corner_detector_reports_side_and_transverse_centre():
    pose_x = 0.35
    corner = detect_lane_corner(render((pose_x, 0.0, 0.0), l_corner("LEFT")),
                                GROUND, **CORNER_KW)
    assert corner is not None
    assert corner.side == "LEFT"
    assert corner.distance_m == pytest.approx(X_T - pose_x - CAM_X, abs=0.01)


def test_l_corner_turns_left_and_reacquires_the_new_lane():
    log, tracker = drive(l_corner("LEFT"), steps=90)
    states = [state for state, _, _ in log]
    assert "APPROACH" in states and "TURN" in states
    assert all(obs is not None for _, obs, _ in log), "no fail-closed frame on a clean corner"
    # The pivot starts where the transverse centre is one half-width ahead.
    first_turn = states.index("TURN")
    assert log[first_turn][2][0] == pytest.approx(X_T - H, abs=0.02)
    turning = [obs for state, obs, _ in log if state == "TURN"]
    assert all(obs == LaneObservation(error=-1.0, confidence=1.0) for obs in turning)
    # Back in FOLLOW, heading down the new lane, near its centre line.
    assert tracker.state == "FOLLOW"
    last_turn = max(i for i, s in enumerate(states) if s == "TURN")
    assert last_turn < len(states) - 20
    _, final_obs, (fx, _fy, fyaw) = log[-1]
    assert fyaw == pytest.approx(math.pi / 2, abs=math.radians(10))
    assert fx == pytest.approx(X_T - H, abs=0.03)
    assert abs(final_obs.error) < 0.2


def test_mirror_corner_turns_right():
    log, tracker = drive(l_corner("RIGHT"), steps=90)
    turning = [obs for state, obs, _ in log if state == "TURN"]
    assert turning and all(obs.error == 1.0 for obs in turning)
    assert tracker.state == "FOLLOW"
    assert log[-1][2][2] == pytest.approx(-math.pi / 2, abs=math.radians(10))


def test_single_frame_transverse_flash_does_not_commit():
    tracker = LaneCornerTracker(camera_x_offset_m=CAM_X)
    flash = render((0.35, 0.0, 0.0), l_corner("LEFT"))
    assert detect_lane_corner(flash, GROUND, **CORNER_KW) is not None
    x = 0.30
    for k in range(20):
        frame = flash if k == 5 else render((x, 0.0, 0.0), straight_lane())
        tracker.update(k * DT, (x, 0.0, 0.0), frame, GROUND, **KW)
        assert tracker.state == "FOLLOW"
        x += 0.01


def test_no_odometry_never_turns():
    log, _ = drive(l_corner("LEFT"), steps=90, odom=False)
    assert {state for state, _, _ in log} == {"FOLLOW"}
    assert all(obs is None or obs.error != -1.0 for _, obs, _ in log)


def test_turn_without_reacquire_fails_closed_past_105_deg():
    tracker, (x, y, yaw), now = _into_turn()
    blank = np.full((HT, W), FLOOR, dtype=np.uint8)
    outputs = []
    turned = 0.0
    for _ in range(12):
        turned += 10.0
        now += DT
        obs = tracker.update(now, (x, y, yaw + math.radians(turned)), blank, GROUND, **KW)
        outputs.append((turned, obs))
    for degrees, obs in outputs:
        if degrees <= 105.0:
            assert obs == LaneObservation(error=-1.0, confidence=1.0)
    first_none = next(d for d, obs in outputs if obs is None)
    assert 105.0 < first_none <= 115.0
    assert tracker.state == "FOLLOW"


def test_turn_that_takes_too_long_fails_closed():
    tracker, (x, y, yaw), started = _into_turn()
    blank = np.full((HT, W), FLOOR, dtype=np.uint8)
    now, result = started, LaneObservation(error=-1.0, confidence=1.0)
    while result is not None:
        yaw += math.radians(1.0)
        now += DT
        result = tracker.update(now, (x, y, yaw), blank, GROUND, **KW)
        assert now - started < 7.0
    assert now - started > 6.0
    assert tracker.state == "FOLLOW"


def test_approach_aborts_on_lateral_drift():
    tracker = LaneCornerTracker(camera_x_offset_m=CAM_X)
    x, now = 0.0, 0.0
    while tracker.state != "APPROACH":
        tracker.update(now, (x, 0.0, 0.0), render((x, 0.0, 0.0), l_corner()), GROUND, **KW)
        x += 0.01
        now += DT
        assert x < 0.6, "never committed"
    result = tracker.update(now, (x, H * 0.6, 0.0), render((x, 0.0, 0.0), l_corner()),
                            GROUND, **KW)
    assert result is None
    assert tracker.state == "FOLLOW"


def test_losing_odometry_mid_manoeuvre_fails_closed():
    tracker, pose, now = _into_turn()
    assert tracker.update(now + DT, None, render(pose, l_corner()), GROUND, **KW) is None
    assert tracker.state == "FOLLOW"
