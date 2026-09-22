"""Left AND right boundaries, centre-line following, fallback ladder (spec §4.2)."""

import math

import cv2
import numpy as np
import pytest

from control.sensing.lane_bev import MEMORY_CONFIDENCE, MEMORY_TRAVEL_M
from control.sensing.lane_boundaries import (
    BRANCH_MAX_LATERAL, MEMORY_MAX_BEARING_RAD, LaneBoundaryTracker, TIERS,
)
from lane_sim import (  # noqa: E402  (test-directory helper)
    CAM_X, GROUND, H, KW, World, drive, lane, offset_polyline, stl_world,
)


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
    """The wall ring's 5 mm footprint (x -1.405..-1.400) is floor-level STL
    geometry, so it is paint in stl_world, parallel and 0.13 m right of
    the robot driving south: it must not read as a branch."""
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
