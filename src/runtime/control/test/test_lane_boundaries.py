"""Left AND right boundaries, centre-line following, fallback ladder (spec §4.2)."""

import math

import cv2
import numpy as np
import pytest
import yaml

from control.sensing.body import WHEEL_R, WHEEL_Y
from control.sensing.perception.lane_bev import MEMORY_CONFIDENCE, MEMORY_TRAVEL_M
from control.sensing.perception.lane_boundaries import (
    BRANCH_MAX_LATERAL, MEMORY_MAX_BEARING_RAD, ONE_MAX_CONFIDENCE, LaneBoundaryTracker, TIERS,
)
from lane_sim import (  # noqa: E402  (test-directory helper)
    CAM_X, GROUND, H, KW, ROOT, World, drive, lane, offset_polyline, stl_world,
)

#: The robot's own widest lateral extent (the wheel track), pinky.urdf.xacro
#: via control.sensing.body: 0.04055 + 0.028 = 0.06855 m. Narrower than
#: URDF_RADIUS (0.076 m, which also covers the forward caster reach and is
#: not what a *side* clearance at a corner needs to clear).
ROBOT_HALF_WIDTH_M = WHEEL_Y + WHEEL_R
#: Assembly/paint tolerance margin beyond the bare wheel track.
CORNER_CLEARANCE_MARGIN_M = 0.003


def tracker():
    return LaneBoundaryTracker(camera_x_offset_m=CAM_X)


STRAIGHT = np.array([(-1.0, 0.0), (1.4, 0.0)])


def test_tiers_are_the_spec_ladder():
    assert TIERS == ("BOTH", "ONE", "MEMORY", "STOP")


def test_straight_lane_uses_both_lines_and_holds_the_centre():
    t = tracker()
    log, pose = drive(lane(STRAIGHT), t, steps=60, pose=(-0.9, 0.0, 0.0))
    assert t.tier == "BOTH"
    assert max(abs(p[1]) for p, _, _ in log[5:]) < 0.005


def test_offset_start_converges_to_the_centre_between_the_lines():
    t = tracker()
    log, pose = drive(lane(STRAIGHT), t, steps=90, pose=(-0.9, -0.03, 0.0))
    assert abs(pose[1]) < 0.006
    assert t.tier == "BOTH"


def test_centre_is_midway_even_when_the_lane_is_narrower_than_assumed():
    """The midpoint uses both lines: a 150 mm lane (h=0.075 real vs 0.0925
    assumed) is still followed at its middle, where a one-line offset would
    sit 17.5 mm off-centre."""
    world = World().line(offset_polyline(STRAIGHT, 0.075)).line(offset_polyline(STRAIGHT, -0.075))
    t = tracker()
    log, pose = drive(world, t, steps=90, pose=(-0.9, 0.0, 0.0))
    assert abs(pose[1]) < 0.006


def test_one_line_visible_falls_to_tier_one():
    """Only the left line after x=0.2: the tracker keeps a half-width off it."""
    world = World().line(offset_polyline(STRAIGHT, H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (0.2, 0.0)]), -H))
    t = tracker()
    tiers = []
    log, pose = drive(world, t, steps=120, pose=(-0.9, 0.0, 0.0),
                      stop=lambda p, k: tiers.append(t.tier) or p[0] > 1.0)
    assert "BOTH" in tiers and "ONE" in tiers
    assert max(abs(p[1]) for p, _, _ in log) < 0.02


def test_one_tier_is_capped_below_both():
    """Design 4.2: a lower tier gets a lower speed cap. BOTH reaches full
    confidence; with one line left, confidence stays at or under
    ONE_MAX_CONFIDENCE."""
    world = World().line(offset_polyline(STRAIGHT, H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (0.2, 0.0)]), -H))
    t = tracker()
    seen = []
    log, _ = drive(world, t, steps=120, pose=(-0.9, 0.0, 0.0),
                   stop=lambda p, k: seen.append(t.tier) or p[0] > 1.0)
    both = [obs.confidence for (_, obs, _), tier in zip(log, seen) if tier == "BOTH"]
    one = [obs.confidence for (_, obs, _), tier in zip(log, seen) if tier == "ONE"]
    assert max(both) == 1.0
    assert one and max(one) <= ONE_MAX_CONFIDENCE


@pytest.mark.parametrize("side", [1.0, -1.0])
def test_90_degree_corner_is_turned_on_the_centre_without_an_opening(side):
    """A 90 deg lane corner (left +1, right -1): the inner line leaves the
    field of view and the outer one carries the turn (ONE). It is a convex
    corner, not a mouth: no OPENS signal.

    A raw distance-to-the-mitred-centreline bound is a proxy for what
    actually matters: the physical robot must not run over the real block
    this corner turns around. That block's inner corner sits at the sharp
    (unmitred) vertex the two boundary lines are offset from -- centreline
    corner (0.2, 0.0) pulled in by the lane half-width on both legs, i.e.
    (0.2 - H, side * H) -- so the bound is instead the clearance from that
    point, which must stay outside the robot's own half-width
    (ROBOT_HALF_WIDTH_M, the wheel track) plus a small margin
    (CORNER_CLEARANCE_MARGIN_M). Measured: side=+1 -> 0.0736 m,
    side=-1 -> 0.0730 m, both above the 0.0716 m bound."""
    centre = np.array([(-1.0, 0.0), (0.2, 0.0), (0.2, 0.8 * side)])
    t = tracker()
    frames = []
    log, pose = drive(lane(centre), t, steps=200, pose=(-0.6, 0.0, 0.0),
                      stop=lambda p, k: frames.append((t.tier, t.last.get("junction")))
                      or p[1] * side > 0.5)
    tiers = [tier for tier, _ in frames]
    signals = {signal for _, signal in frames}
    vertex = (0.2 - H, side * H)
    clearance = min(math.hypot(p[0] - vertex[0], p[1] - vertex[1]) for p, _, _ in log)
    assert clearance >= ROBOT_HALF_WIDTH_M + CORNER_CLEARANCE_MARGIN_M
    assert "STOP" not in tiers and "ONE" in tiers
    assert pose[1] * side > 0.5
    assert abs(math.remainder(pose[2] - side * math.pi / 2, 2 * math.pi)) < math.radians(10)
    assert not signals & {"LEFT_OPENS", "RIGHT_OPENS"}


def test_lost_lines_step_down_through_memory_to_stop():
    """Both lines end at x=-0.3. Memory carries the centre a bounded way,
    then the output stops. It must not pursue the iso-line loop round the
    dead end: lane_bev's support test alone accepts points past a round end
    cap, and that loop turned the robot 128 deg (END_AXIS_RADIUS_M)."""
    world = World().line(offset_polyline(np.array([(-1.0, 0.0), (-0.3, 0.0)]), H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (-0.3, 0.0)]), -H))
    t = tracker()
    tiers, blind = [], []

    def record(p, k):
        tiers.append(t.tier)
        blind.append(t.last.get("left_label") is None and t.last.get("right_label") is None)
        return False

    log, pose = drive(world, t, steps=200, pose=(-0.9, 0.0, 0.0), stop=record)
    assert tiers.index("MEMORY") < tiers.index("STOP")
    assert tiers[-1] == "STOP"
    first_blind = blind.index(True)
    travel = sum(math.dist(a[:2], b[:2])
                 for (a, _, _), (b, _, _) in zip(log[first_blind:], log[first_blind + 1:]))
    assert travel <= MEMORY_TRAVEL_M
    assert abs(pose[2]) < math.radians(30)


def test_unsupported_fresh_line_falls_to_the_other_sides_memory():
    """The ladder, on the target-choice hook: the left line is seen but
    ends 0.12 m ahead, so no iso-line point at 0.15-0.25 m is supported;
    the right line is only remembered, reaching 0.45 m ahead. The tracker
    falls to MEMORY on the right memory instead of STOP.

    Closed loop cannot pose this on a straight: a line 0.08 m to the side
    leaves the 66 deg field of view (x >= 0.157 m) before its lookahead
    runs out (x < 0.16 m)."""
    t = tracker()
    view = t._birds_eye(GROUND, lane(STRAIGHT).render((0.0, 0.0, 0.0)).shape)
    left = (((view.y >= H - 0.0125) & (view.y <= H + 0.0125) & (view.x <= 0.12))
            | (np.hypot(view.x - 0.12, view.y - H) <= 0.0125)).astype(np.uint8)
    right = ((view.y >= -H - 0.0125) & (view.y <= -H + 0.0125)
             & (view.x <= 0.45)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(left, connectivity=4)
    found = {"left": 1, "right": None, "labels": labels, "stats": stats, "count": count,
             "left_grid": left, "right_grid": right, "fresh_length": 0.3}
    obs = t._pursue(view, found, H)
    assert t.tier == "MEMORY"
    assert obs is not None and obs.confidence == MEMORY_CONFIDENCE
    x, y = t.last["target"]
    assert abs(y) < 0.005 and x >= 0.15
    assert abs(math.atan2(y, x)) <= MEMORY_MAX_BEARING_RAD


def test_memory_bearing_bound_refuses_a_line_across_the_path():
    """Only the bound blocks this: nothing is seen and the one remembered
    line runs across the path 0.14 m ahead. Its iso-line (x = 0.06 m) meets
    the 0.15 m lookahead ring at 66 deg, a supported interior point, but
    pursuing it on memory alone would demand a tighter turn than any lane
    centre on the track."""
    t = tracker()
    view = t._birds_eye(GROUND, lane(STRAIGHT).render((0.0, 0.0, 0.0)).shape)
    across = ((np.abs(view.x - 0.14) <= 0.0125) & (np.abs(view.y) <= 0.30)).astype(np.uint8)
    empty = np.zeros_like(across)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(empty, connectivity=4)
    found = {"left": None, "right": None, "labels": labels, "stats": stats, "count": count,
             "left_grid": across, "right_grid": empty, "fresh_length": 0.0}
    assert t._pursue(view, found, H) is None
    assert t.tier == "STOP"
    x, y = t.last["target"]
    assert abs(math.atan2(y, x)) > MEMORY_MAX_BEARING_RAD


def test_no_ground_or_no_odometry_is_no_output():
    t = tracker()
    frame = lane(STRAIGHT).render((-0.9, 0.0, 0.0))
    assert t.update(0.0, None, frame, GROUND, **KW) is None
    assert t.update(0.0, (-0.9, 0.0, 0.0), frame, None, **KW) is None
    assert t.tier == "STOP"


def test_crosswalk_bars_between_the_lines_are_not_boundaries():
    world = lane(STRAIGHT)
    for y in (-0.05, -0.017, 0.017, 0.05):
        world.rect(0.2, y, 0.121, 0.02)
    t = tracker()
    log, pose = drive(world, t, steps=120, pose=(-0.9, 0.0, 0.0), stop=lambda p, k: p[0] > 0.7)
    assert max(abs(p[1]) for p, _, _ in log) < 0.015


def test_opening_on_one_side_raises_the_junction_signal():
    """The right line ends while the left continues: a mouth opens on the right."""
    world = World().line(offset_polyline(STRAIGHT, H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (0.0, 0.0)]), -H))
    t = tracker()
    signals = []
    drive(world, t, steps=100, pose=(-0.9, 0.0, 0.0),
          stop=lambda p, k: signals.append(t.last.get("junction")) or p[0] > 0.3)
    assert "RIGHT_OPENS" in signals


def _signals(world, steps=100, stop_x=0.3):
    t = tracker()
    signals = []
    drive(world, t, steps=steps, pose=(-0.9, 0.0, 0.0),
          stop=lambda p, k: signals.append(t.last.get("junction")) or p[0] > stop_x)
    return signals


def test_branch_line_leaving_at_45_degrees_ahead_raises_branch():
    """A mouth on the right: the right line stops at x=0.05 and the branch's
    edge leaves from x=0.10 at 45 deg, its near end inside the corridor."""
    start = np.array([0.10, -H])
    branch = np.array([start, start + 0.6 * np.array([math.cos(-math.pi / 4),
                                                      math.sin(-math.pi / 4)])])
    world = World().line(offset_polyline(STRAIGHT, H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (0.05, 0.0)]), -H)).line(branch)
    assert "BRANCH" in _signals(world, stop_x=0.1)


def test_parallel_line_outside_the_lane_is_not_a_branch():
    """A line 40 mm outside the right boundary, inside the extended corridor
    (|y| <= BRANCH_MAX_LATERAL h), runs along the lane: no branch."""
    lateral = H + 0.04
    assert lateral <= BRANCH_MAX_LATERAL * H
    world = lane(STRAIGHT).line(offset_polyline(STRAIGHT, -lateral))
    assert "BRANCH" not in _signals(world, stop_x=0.8, steps=120)


@pytest.fixture(scope="module")
def west():
    return stl_world()


def test_west_straight_raises_no_branch_either_way(west):
    """stl_scene counts the perimeter wall's bottom faces (x -1.405..-1.400)
    as floor, so stl_world paints a 5 mm strip there, parallel and 0.13 m
    right of the robot driving south. A host-test-only artefact (in Gazebo
    the wall stands on it and hides it), but a fair parallel-line case: it
    must not read as a branch."""
    centre_x = -1.2696
    for yaw, y0, stop_y in ((-math.pi / 2, 0.30, -0.35), (math.pi / 2, -0.30, 0.35)):
        t = tracker()
        signals = []
        drive(west, t, steps=120, pose=(centre_x, y0, yaw),
              stop=lambda p, k: signals.append(t.last.get("junction"))
              or ((p[1] < stop_y) if yaw < 0 else (p[1] > stop_y)))
        assert "BRANCH" not in signals


def test_west_loop_both_directions_stay_in_the_lane(west):
    """Left lane of the 260919 track, driven south (start) and north (reverse):
    left/right roles swap, the centre rule does not care."""
    world = west
    centre_x = -1.2696
    for yaw, y0, stop_y in ((-math.pi / 2, 0.30, -0.35), (math.pi / 2, -0.30, 0.35)):
        t = tracker()
        log, pose = drive(world, t, steps=120, pose=(centre_x, y0, yaw),
                          stop=lambda p, k: (p[1] < stop_y) if yaw < 0 else (p[1] > stop_y))
        assert max(abs(p[0] - centre_x) for p, _, _ in log) < 0.02


def _east_start():
    """lane_graph.yaml east segment, point 150: the S-curve at x ~0.73 m."""
    graph = yaml.safe_load((ROOT / "map" / "map_v2_fleet" / "lane_graph.yaml").read_text(
        encoding="utf-8"))
    points = np.array(graph["segments"]["east"]["points"])
    (x, y), (x1, y1) = points[150], points[151]
    return (float(x), float(y), math.atan2(y1 - y, x1 - x))


@pytest.mark.parametrize("start", ["east_curve", "west_chevron"])
def test_curves_raise_no_branch(west, start):
    """No branch lines on these curves. The raw BRANCH test flickered on
    single frames here: at the east S-curve, and where the lap leaves the
    ring for the top corridor (lap step ~350, west segment). There, a
    sliver beside the right line's diagonal leg read 25-64 deg against the
    heading, though parallel to the line it lies beside."""
    pose = _east_start() if start == "east_curve" else (-0.569, 0.016, 7.826 - 2 * math.pi)
    t = tracker()
    signals = []
    drive(west, t, steps=70 if start == "east_curve" else 60, pose=pose,
          stop=lambda p, k: signals.append(t.last.get("junction")) or False)
    assert "BRANCH" not in signals
