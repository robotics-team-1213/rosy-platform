"""Left AND right boundaries, centre-line following, fallback ladder (spec §4.2)."""

import math

import numpy as np

from control.sensing.lane_boundaries import LaneBoundaryTracker, TIERS
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
    world = World().line(offset_polyline(np.array([(-1.0, 0.0), (-0.3, 0.0)]), H)).line(
        offset_polyline(np.array([(-1.0, 0.0), (-0.3, 0.0)]), -H))
    t = tracker()
    tiers = []
    drive(world, t, steps=200, pose=(-0.9, 0.0, 0.0),
          stop=lambda p, k: tiers.append(t.tier) or False)
    assert tiers.index("MEMORY") < tiers.index("STOP")
    assert tiers[-1] == "STOP"


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


def test_west_loop_both_directions_stay_in_the_lane():
    """Left lane of the 260919 track, driven south (start) and north (reverse):
    left/right roles swap, the centre rule does not care."""
    world = stl_world()
    centre_x = -1.2696
    for yaw, y0, stop_y in ((-math.pi / 2, 0.30, -0.35), (math.pi / 2, -0.30, 0.35)):
        t = tracker()
        log, pose = drive(world, t, steps=120, pose=(centre_x, y0, yaw),
                          stop=lambda p, k: (p[1] < stop_y) if yaw < 0 else (p[1] > stop_y))
        assert max(abs(p[0] - centre_x) for p, _, _ in log) < 0.02
