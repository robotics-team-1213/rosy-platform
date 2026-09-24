"""Left-edge lane following in bird's-eye view (edge_left camera lane mode).

Gazebo run 184434 turned the first 90 deg corner, then stopped fail-closed
where both lines bend 65 deg towards the roundabout: row-wise pairing reads a
diagonal line as one wide run. Frames here are rendered by inverse projection
from a pose through the declared Gazebo camera, over a 1 mm floor raster, and
the loop is closed with CORE's line_follow law, so each case is judged by
where the robot actually drives.
"""

import math
import re
from pathlib import Path

import numpy as np
import pytest

from control.sensing.camera_ground import simulation_ground_plane
from control.sensing.lane import LaneCornerTracker, LaneObservation
from control.sensing import lane_bev
from control.sensing.lane_bev import (
    BirdsEye,
    LaneEdgeFollower,
    error_for_curvature,
    pose_if_fresh,
)
from lane_sim import (  # noqa: E402  (test-directory helper)
    CAM_X, DT, FLOOR, GROUND, H, HT, KW, START, W, World,
    core_command, distance_to_polyline as _distance_to_polyline, lane,
    stl_world as _stl_world,
)
from lane_sim import drive as _drive

ROOT = Path(__file__).resolve().parents[1]


def drive(world, *, steps, pose=(0.0, 0.0, 0.0), follower=None, odom=True, stop=None):
    return _drive(world, follower or LaneEdgeFollower(camera_x_offset_m=CAM_X),
                  steps=steps, pose=pose, odom=odom, stop=stop)


# --- CORE mapping ------------------------------------------------------------

def test_core_law_mirror_matches_core_defaults():
    config = (ROOT.parents[1] / "core/core/config/rosy_default.yaml").read_text(encoding="utf-8")
    block = config.split("line_follow:", 1)[1]

    def value(key):
        return float(re.search(key + r":\s*([0-9.]+)", block).group(1))

    assert value("cruise_speed") == lane_bev.CORE_CRUISE_M_S
    assert value("steering_gain") == lane_bev.CORE_STEERING_GAIN
    assert value("min_confidence") == lane_bev.CORE_MIN_CONFIDENCE
    assert value("stale_after_s") == lane_bev.ODOM_MAX_SKEW_S
    manager = (ROOT.parents[1] / "core/core_features/core_features/line_follow/manager.py"
               ).read_text(encoding="utf-8")
    assert "max(0.2, 1.0 - 0.65 * abs(error))" in manager
    assert lane_bev.CORE_CURVE_SLOWDOWN == 0.65


@pytest.mark.parametrize("curvature", [-8.0, -2.0, 0.0, 1.0, 4.0, 10.8])
@pytest.mark.parametrize("confidence", [0.6, 0.8, 1.0])
def test_error_for_curvature_makes_core_drive_that_curvature(curvature, confidence):
    e = error_for_curvature(curvature, confidence)
    v, w = core_command(LaneObservation(error=e, confidence=confidence))
    assert v > 0.0
    assert w / v == pytest.approx(curvature, abs=1e-6)
    assert (e < 0) == (curvature > 0) or curvature == 0.0


def test_birds_eye_cells_image_the_floor_they_stand_for():
    view = BirdsEye(GROUND, W, HT, CAM_X)
    i, j = np.nonzero(view.observable)
    assert len(i) > 1000
    for k in range(0, len(i), 997):
        x, y = view.x[i[k], j[k]], view.y[i[k], j[k]]
        row, col = view._pixel_row[i[k], j[k]], view._pixel_col[i[k], j[k]]
        assert GROUND.distance(row) == pytest.approx(x - CAM_X, abs=0.012)
        assert -GROUND.lateral(col, row) == pytest.approx(y, abs=0.006)


# --- Fail-closed and seeding ---------------------------------------------------

def test_measured_far_paint_dimming_defeats_the_row_mode_threshold():
    """At 220 the far half of each line is lost (run 193728 never seeded)."""
    world = lane([(-1.0, 0.0), (2.0, 0.0)])
    frame = world.render((0.0, 0.0, 0.0))
    strict = LaneEdgeFollower(camera_x_offset_m=CAM_X)
    assert strict.update(0.0, (0.0, 0.0, 0.0), frame, GROUND, **dict(KW, bright_threshold=220)
                         ) is None
    assert LaneEdgeFollower(camera_x_offset_m=CAM_X).update(
        0.0, (0.0, 0.0, 0.0), frame, GROUND, **KW) is not None


def test_no_ground_or_no_odometry_is_no_output():
    world = lane([(-1.0, 0.0), (1.5, 0.0)])
    follower = LaneEdgeFollower(camera_x_offset_m=CAM_X)
    frame = world.render((0.0, 0.0, 0.0))
    assert follower.update(0.0, (0.0, 0.0, 0.0), frame, None, **KW) is None
    assert follower.update(0.2, None, frame, GROUND, **KW) is None
    log, _ = drive(world, steps=10, odom=False)
    assert all(obs is None for _, obs, _ in log)


def test_one_line_alone_never_seeds():
    """No lane-width pair, no memory: a lone line at +h is not trusted."""
    world = World().line([(-1.0, H), (1.5, H)])
    log, _ = drive(world, steps=10)
    assert all(obs is None for _, obs, _ in log)


# --- Straight, bend, arc, crosswalk -------------------------------------------

def test_straight_lane_holds_the_centre():
    log, pose = drive(lane([(-1.0, 0.0), (2.0, 0.0)]), steps=60, pose=(0.0, 0.02, 0.0))
    assert all(obs is not None for _, obs, _ in log)
    assert abs(pose[1]) < 0.005
    assert abs(pose[2]) < math.radians(3)
    assert log[-1][1].confidence == 1.0
    assert pose[0] > 0.8


@pytest.mark.parametrize("side", [1.0, -1.0])
def test_65_degree_bend_is_followed(side):
    """The 260919 chevrons: both lines bend ~65 deg (run 184434 stopped here)."""
    turn = side * math.radians(65.0)
    centre = [(-1.0, 0.0), (0.45, 0.0),
              (0.45 + 1.2 * math.cos(turn), 1.2 * math.sin(turn))]
    log, pose = drive(lane(centre), steps=70)
    assert all(obs is not None for _, obs, _ in log)
    assert pose[2] == pytest.approx(turn, abs=math.radians(6))
    assert _distance_to_polyline(pose[:2], np.array(centre)) < 0.015
    worst = max(_distance_to_polyline(p[:2], np.array(centre)) for p, _, _ in log)
    assert worst < 0.04


def test_roundabout_outer_arc_is_held_at_a_half_width():
    """Ring outer (left) line r=0.348, island r=0.155 from the STL; the
    path a half-width inside the outer line has r=0.255. As on the track,
    the robot arrives with memory: a straight run-in joins the arc
    tangentially (the island's near side is never in view), and the outer
    ring is open where the run-in lane enters it."""
    centre = np.array([0.0, -0.2552])
    world = World()
    for radius, sweep in ((0.3477, math.radians(290.0)), (0.155, 2.0 * math.pi)):
        a = np.linspace(math.pi / 2, math.pi / 2 - sweep, 721)
        arc = np.stack([centre[0] + radius * np.cos(a), centre[1] + radius * np.sin(a)], axis=1)
        world.line(np.vstack([[(-1.0, arc[0, 1])], arc]))
    log, _ = drive(world, steps=110, pose=(-0.5, 0.0, 0.0))
    assert all(obs is not None for _, obs, _ in log)
    on_arc = [p for p, _, _ in log if p[0] > 0.05 or p[1] < -0.05]
    assert len(on_arc) > 40
    radii = [math.dist(p[:2], centre) for p in on_arc]
    assert max(abs(r - 0.2552) for r in radii) < 0.02
    turned = log[-1][0][2] - log[0][0][2]
    assert turned < -math.radians(120)


def test_crosswalk_bars_do_not_pull_the_path():
    """The lap's left-lane crosswalk from the STL: bars 0.026 x 0.121 m at
    -0.059, -0.019, +0.021, +0.061 m from the centre, parallel to travel,
    6 mm short of the boundary lines."""
    world = lane([(-1.0, 0.0), (2.0, 0.0)])
    for lateral in (-0.059, -0.019, 0.021, 0.061):
        world.rect(0.55, lateral, 0.121, 0.026)
    log, pose = drive(world, steps=60)
    assert all(obs is not None for _, obs, _ in log)
    assert max(abs(p[1]) for p, _, _ in log) < 0.01
    assert pose[0] > 0.8


# --- Corners -----------------------------------------------------------------

def l_corner_world(side=1.0):
    """Lane along +x turning 90 deg to `side` (left +1): the inner line ends,
    the outer line crosses ahead, like the 260919 left-lane corner."""
    x_t = 0.60
    s = side
    world = World()
    world.line([(-1.0, -s * H), (x_t, -s * H), (x_t, s * 1.0)])            # outer
    world.line([(-1.0, s * H), (x_t - 2 * H, s * H), (x_t - 2 * H, s * 1.0)])  # inner
    return world, x_t


@pytest.mark.parametrize("side", [1.0, -1.0])
def test_l_corner_is_turned_into_the_new_lane(side):
    world, x_t = l_corner_world(side)
    follower = LaneEdgeFollower(camera_x_offset_m=CAM_X, corner_handoff=True)
    log, pose = drive(world, steps=90, follower=follower)
    assert all(obs is not None for _, obs, _ in log)
    assert pose[2] == pytest.approx(side * math.pi / 2, abs=math.radians(8))
    assert pose[0] == pytest.approx(x_t - H, abs=0.03)
    assert side * pose[1] > 0.3


def test_corner_tracker_holds_commit_until_allowed_then_uses_armed_corner():
    world, x_t = l_corner_world()
    tracker = LaneCornerTracker(camera_x_offset_m=CAM_X)
    x = 0.20
    for k in range(10):
        tracker.update(k * DT, (x, 0.0, 0.0), world.render((x, 0.0, 0.0)), GROUND,
                       commit_allowed=False, **KW)
        assert tracker.state == "FOLLOW"
        x += 0.012
    assert tracker._armed is not None
    # Near the pivot the corner is no longer detectable, but it is armed.
    x = x_t - 0.19
    blank = np.full((HT, W), FLOOR, np.uint8)
    obs = tracker.update(3.0, (x, 0.0, 0.0), blank, GROUND, **KW)
    assert tracker.state == "APPROACH"
    assert obs == LaneObservation(error=0.0, confidence=0.6)


def test_armed_corner_expires_once_the_robot_has_turned():
    world, _ = l_corner_world()
    tracker = LaneCornerTracker(camera_x_offset_m=CAM_X)
    x = 0.20
    for k in range(4):
        tracker.update(k * DT, (x, 0.0, 0.0), world.render((x, 0.0, 0.0)), GROUND,
                       commit_allowed=False, **KW)
        x += 0.012
    assert tracker._armed is not None
    blank = np.full((HT, W), FLOOR, np.uint8)
    tracker.update(1.0, (x, 0.0, math.radians(40)), blank, GROUND, commit_allowed=False, **KW)
    assert tracker._armed is None
    tracker.update(1.2, (x, 0.0, math.radians(40)), blank, GROUND, **KW)
    assert tracker.state == "FOLLOW"


def test_edge_failure_hands_off_to_an_armed_corner(monkeypatch):
    world, x_t = l_corner_world()
    follower = LaneEdgeFollower(camera_x_offset_m=CAM_X, corner_handoff=True)
    real = follower._follow

    def failing_follow(now_s, pose, *args):
        result = real(now_s, pose, *args)
        return None if pose[0] > x_t - 0.25 else result

    monkeypatch.setattr(follower, "_follow", failing_follow)
    log, pose = drive(world, steps=90, follower=follower)
    states = [state for _, _, state in log]
    assert "CORNER_APPROACH" in states and "CORNER_TURN" in states
    assert pose[2] == pytest.approx(math.pi / 2, abs=math.radians(20))


# --- Loss ------------------------------------------------------------------------

def test_boundary_truly_lost_ends_in_no_output():
    """Paint vanishes: memory carries the path a bounded distance at
    MEMORY_CONFIDENCE, then the output is None and CORE stops."""
    full = lane([(-1.0, 0.0), (2.0, 0.0)])
    empty = World()
    follower = LaneEdgeFollower(camera_x_offset_m=CAM_X)
    pose, travel_blind, outputs = (0.0, 0.0, 0.0), 0.0, []
    for k in range(80):
        blind = k >= 15
        obs = follower.update(k * DT, pose, (empty if blind else full).render(pose), GROUND, **KW)
        if blind:
            outputs.append(obs)
        v, w = core_command(obs)
        pose = (pose[0] + v * DT * math.cos(pose[2]), pose[1] + v * DT * math.sin(pose[2]),
                pose[2] + w * DT)
        if blind:
            travel_blind += v * DT
    assert outputs[0] is not None and outputs[0].confidence == lane_bev.MEMORY_CONFIDENCE
    assert outputs[-1] is None
    assert travel_blind <= lane_bev.MEMORY_TRAVEL_M


# --- The 260919 lap ---------------------------------------------------------------

def test_full_lap_of_the_260919_track_returns_to_the_start():
    """Left lane -> 90 deg corner -> bottom corridor -> 65 deg chevron ->
    roundabout outer arc -> chevron -> top corridor -> 90 deg corner. The
    lane-centre loop is ~3.1 m."""
    world = _stl_world()
    follower = LaneEdgeFollower(camera_x_offset_m=CAM_X, corner_handoff=True)
    travelled = {"m": 0.0, "last": START}

    def home(pose, _k):
        travelled["m"] += math.dist(pose[:2], travelled["last"][:2])
        travelled["last"] = pose
        return travelled["m"] > 2.5 and math.dist(pose[:2], START[:2]) < 0.05

    log, pose = drive(world, steps=600, pose=START, follower=follower, stop=home)
    nones = sum(obs is None for _, obs, _ in log)
    assert nones == 0
    assert 2.8 < travelled["m"] < 3.4
    assert math.dist(pose[:2], START[:2]) < 0.15
    heading = math.atan2(math.sin(pose[2] - START[2]), math.cos(pose[2] - START[2]))
    assert abs(heading) < math.radians(20)


# --- Stale or frozen odometry (review of bb85da6) --------------------------------

def test_memory_max_age_is_memory_travel_at_the_slowest_memory_speed():
    """The slowest speed CORE commands on memory alone: MEMORY_CONFIDENCE on
    the tightest path the lap asks for (radius one half-width)."""
    e = error_for_curvature(1.0 / H, lane_bev.MEMORY_CONFIDENCE)
    slowest, _ = core_command(LaneObservation(error=e, confidence=lane_bev.MEMORY_CONFIDENCE))
    assert lane_bev.MEMORY_MAX_AGE_S == pytest.approx(lane_bev.MEMORY_TRAVEL_M / slowest,
                                                      rel=0.02)


def test_frozen_odometry_cannot_drive_on_memory_past_its_age():
    """Reviewer repro: seed, then blank floor while odometry repeats the same
    pose. Travel never grows, so only a clock can end the memory."""
    full = lane([(-1.0, 0.0), (2.0, 0.0)])
    empty = World()
    follower = LaneEdgeFollower(camera_x_offset_m=CAM_X)
    pose = (0.0, 0.0, 0.0)
    for k in range(15):
        follower.update(k * DT, pose, full.render(pose), GROUND, **KW)
    last_fresh = 14 * DT
    outputs = []
    for k in range(15, 15 + 3000):
        outputs.append((k * DT, follower.update(k * DT, pose, empty.render((0.5, 0.0, 0.0)),
                                                GROUND, **KW)))
    driven = [t for t, obs in outputs if obs is not None]
    assert driven and max(driven) - last_fresh <= lane_bev.MEMORY_MAX_AGE_S
    assert all(obs is None for t, obs in outputs if t - last_fresh > lane_bev.MEMORY_MAX_AGE_S)
    # Forgotten, not merely silent: the same boundary must reseed from scratch.
    assert not follower._left and not follower._right


def test_stale_odometry_stamp_is_no_pose_and_no_output():
    assert pose_if_fresh((1.0, 2.0, 0.3), 10.0, 10.2) == (1.0, 2.0, 0.3)
    assert pose_if_fresh((1.0, 2.0, 0.3), 10.0, 10.0 + lane_bev.ODOM_MAX_SKEW_S + 0.01) is None
    assert pose_if_fresh((1.0, 2.0, 0.3), 10.5, 10.0) is None   # odom from the future
    assert pose_if_fresh(None, None, 10.0) is None
    assert pose_if_fresh((1.0, 2.0, 0.3), float("nan"), 10.0) is None
    assert pose_if_fresh((1.0, 2.0, 0.3), 10.0, float("inf")) is None
    world = lane([(-1.0, 0.0), (2.0, 0.0)])
    follower = LaneEdgeFollower(camera_x_offset_m=CAM_X)
    pose = (0.0, 0.0, 0.0)
    assert follower.update(0.0, pose, world.render(pose), GROUND, **KW) is not None
    stale = pose_if_fresh(pose, 0.0, 0.2 + lane_bev.ODOM_MAX_SKEW_S + 0.01)
    assert follower.update(0.2, stale, world.render(pose), GROUND, **KW) is None
    assert not follower._left


def test_armed_corner_expires_by_time_without_odometry_motion():
    from control.sensing import lane as lane_module

    world, _ = l_corner_world()
    tracker = LaneCornerTracker(camera_x_offset_m=CAM_X)
    x = 0.20
    for k in range(4):
        tracker.update(k * DT, (x, 0.0, 0.0), world.render((x, 0.0, 0.0)), GROUND,
                       commit_allowed=False, **KW)
        x += 0.012
    assert tracker._armed is not None
    armed_at = 3 * DT
    blank = np.full((HT, W), FLOOR, np.uint8)
    late = armed_at + lane_module.ARMED_MAX_AGE_S + DT
    tracker.update(late, (x, 0.0, 0.0), blank, GROUND, commit_allowed=False, **KW)
    assert tracker._armed is None
    tracker.update(late + DT, (x, 0.0, 0.0), blank, GROUND, **KW)
    assert tracker.state == "FOLLOW"


def test_birds_eye_cache_follows_the_geometry_not_the_object():
    follower = LaneEdgeFollower(camera_x_offset_m=CAM_X)
    frame = lane([(-1.0, 0.0), (2.0, 0.0)]).render((0.0, 0.0, 0.0))
    view = follower._birds_eye(GROUND, frame.shape)
    twin = simulation_ground_plane(
        source="GAZEBO", simulation_enabled=True, use_sim_time=True,
        width_px=W, height_px=HT, height_m=0.060194,
        pitch_rad=math.radians(25.0), hfov_rad=1.1519, max_range_m=0.6)
    assert follower._birds_eye(twin, frame.shape) is view
    tilted = simulation_ground_plane(
        source="GAZEBO", simulation_enabled=True, use_sim_time=True,
        width_px=W, height_px=HT, height_m=0.060194,
        pitch_rad=math.radians(20.0), hfov_rad=1.1519, max_range_m=0.6)
    assert follower._birds_eye(tilted, frame.shape) is not view
