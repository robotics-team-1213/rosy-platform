"""Smooth motion through waypoints: exact where it must be, rounded where it may be, never past the guard."""
import importlib.util
from pathlib import Path

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
spec = importlib.util.spec_from_file_location("motion_profile", OMX / "motion_profile.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

FPS, VMAX = 30, 4.5
RISE_TURN_DESCEND = [[0, -60, 50, 45, 10, 46.6], [0, -27, 18, 46, 10, 46.6],
                     [30, -27, 18, 46, -30, 46.6], [30, -18, 22, 47, -30, 46.6]]


def speeds(frames, start):
    path = [start, *frames]
    return [[(b - a) * FPS for a, b in zip(p, q)] for p, q in zip(path, path[1:])]


def test_a_single_move_starts_and_ends_at_rest_within_the_guard_limits():
    frames = m.smooth(RISE_TURN_DESCEND[:2], FPS, VMAX)
    v = speeds(frames, RISE_TURN_DESCEND[0])
    assert frames[-1] == RISE_TURN_DESCEND[1]
    assert max(abs(x) for row in v for x in row) <= VMAX + 1e-6
    assert max(abs(x) for x in v[0]) < 0.5 and max(abs(x) for x in v[-1]) < 0.5  # no jump at either end
    accel = [max(abs(b - a) * FPS for a, b in zip(p, q)) for p, q in zip(v, v[1:])]
    assert max(accel) <= m.GUARD_ACCEL_UNITS_S2 + 0.5


def test_blended_corners_keep_moving_and_save_time_without_cutting_far():
    exact = m.smooth(RISE_TURN_DESCEND, FPS, VMAX)
    blended = m.smooth(RISE_TURN_DESCEND, FPS, VMAX, blend=[False, True, True, False])
    assert len(blended) < len(exact) and blended[-1] == RISE_TURN_DESCEND[-1]
    v = speeds(blended, RISE_TURN_DESCEND[0])
    assert max(abs(x) for row in v for x in row) <= VMAX + 0.5  # one joint slows as the other speeds up
    accel = [max(abs(b - a) * FPS for a, b in zip(p, q)) for p, q in zip(v, v[1:])]
    assert max(accel) <= 2 * m.GUARD_ACCEL_UNITS_S2 + 0.5
    corner = RISE_TURN_DESCEND[1]
    nearest = min(max(abs(a - b) for a, b in zip(f, corner)) for f in blended)
    assert nearest < 1.0  # the rise-to-turn corner is cut by under a unit
    stopped = [i for i, row in enumerate(v[1:-1]) if max(abs(x) for x in row) < 0.05]
    assert not stopped  # it never comes to rest between the start and the goal


def test_unblended_corners_are_passed_exactly_at_rest():
    frames = m.smooth(RISE_TURN_DESCEND, FPS, VMAX)
    for corner in RISE_TURN_DESCEND[1:]:
        assert min(max(abs(a - b) for a, b in zip(f, corner)) for f in frames) < 0.01  # sampled at rest


@pytest.mark.parametrize("distance", [0.2, 3.0, 40.0])
def test_trapezoid_covers_short_and_long_moves(distance):
    duration, ramp = m.trapezoid(distance, VMAX, 2.5)
    assert m.progress(duration, duration, ramp) == 1.0 and m.progress(duration / 2, duration, ramp) == pytest.approx(0.5)


def test_retime_keeps_the_planned_path_and_eases_in_and_out():
    line = [[0, -30 + k * 0.4, 20 - k * 0.3, 46 + k * 0.1, 10, 46.6] for k in range(1, 26)]  # a planner's line
    start = [0, -30, 20, 46, 10, 46.6]
    frames = m.retime(line, FPS, VMAX, start=start)
    assert frames[-1] == line[-1]
    v = speeds(frames, start)
    assert max(abs(x) for x in v[0]) < 0.5 and max(abs(x) for x in v[-1]) < 0.5  # eases out of and into rest
    assert max(abs(x) for row in v for x in row) <= VMAX + 1e-6
    for f in frames:  # every frame lies on the planned polyline (here a straight joint line)
        k = (f[1] + 30) / 0.4
        assert f[2] == pytest.approx(20 - k * 0.3, abs=1e-6) and f[3] == pytest.approx(46 + k * 0.1, abs=1e-6)
