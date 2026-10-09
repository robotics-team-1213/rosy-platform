"""Closed-loop LaneKeeper diagnostics with the rendered floor and CORE law mirror.

These are host SIM cases, not an approved camera calibration or a device test.
The bend case must either stop safely before a missing parallel boundary or
make measured progress around the turn while staying near the centreline.
"""

import math

import numpy as np

from control.sensing.perception.lane_keep import LaneKeeper
from lane_sim import (CAM_X, DT, GROUND, H, World, core_command,
                      distance_to_polyline, lane, offset_polyline)


def _run(world, centre, start, *, steps=75, bend_expected=False):
    keeper = LaneKeeper(camera_x_offset_m=CAM_X, corner_turning=True)
    pose = start
    records = []
    for step in range(steps):
        observation = keeper.update(world.render(pose), GROUND,
                                    lane_half_width_m=H, bend_expected=bend_expected)
        records.append((pose, observation, dict(keeper.last)))
        linear, angular = core_command(observation)
        middle = pose[2] + angular * DT / 2.0
        pose = (pose[0] + linear * DT * math.cos(middle),
                pose[1] + linear * DT * math.sin(middle), pose[2] + angular * DT)
    return records, pose


def test_keep_crosses_one_missing_straight_boundary_without_leaving_centre():
    centre = np.array([(-1.0, 0.0), (2.0, 0.0)])
    world = lane(centre)
    x0, x1 = 0.35, 0.55
    world.paint[int((world.y1 - H - 0.03) * 1000):int((world.y1 - H + 0.03) * 1000),
                int((x0 - world.x0) * 1000):int((x1 - world.x0) * 1000)] = 0
    records, pose = _run(world, centre, (0.0, 0.0, 0.0))
    gap = [(p, last) for p, obs, last in records if x0 < p[0] < x1]
    assert gap
    assert any(last["strategy"] == "right_only" for _, _, last in records)
    assert all(obs is not None for p, obs, _ in records if p[0] <= 0.8)
    assert pose[0] > 0.8
    assert max(distance_to_polyline(p[:2], centre) for p, _, _ in records) < 0.02


def test_keep_bend_stops_early_or_follows_centreline_through_turn():
    """Characterize either a fail-closed gap or a bounded completed bend."""
    turn = math.radians(65.0)
    centre = np.array([(-1.0, 0.0), (0.45, 0.0),
                       (0.45 + 1.2 * math.cos(turn), 1.2 * math.sin(turn))])
    records, pose = _run(lane(centre), centre, (-0.3, 0.0, 0.0), bend_expected=True)
    stops = [(i, p, last) for i, (p, obs, last) in enumerate(records) if obs is None]
    if stops:
        step, stopped_at, last = stops[0]
        assert 0.23 < stopped_at[0] < 0.30, (step, stopped_at, last)
        assert last["reason"] == "no_boundary", (step, stopped_at, last)
        assert any(c.get("reason") == "bend" for c in last["candidates"]), last
        assert any(row[2]["strategy"] == "bend_ahead" for row in records[:step]), step
        assert all(obs is None for _, obs, _ in records[step:]), stops
        assert pose[:2] == stopped_at[:2], (pose, stopped_at)
        assert distance_to_polyline(pose[:2], centre) < 0.02, pose
        return

    turn_direction = centre[2] - centre[1]
    turn_direction /= np.linalg.norm(turn_direction)
    turn_progress = float(np.dot(np.asarray(pose[:2]) - centre[1], turn_direction))
    errors = [distance_to_polyline(p[:2], centre) for p, _, _ in records]
    errors.append(distance_to_polyline(pose[:2], centre))
    max_error = max(errors)
    diagnostic = (f"final_pose={pose}, turn_progress={turn_progress:.3f} m, "
                  f"max_cross_track={max_error:.3f} m, "
                  f"last_strategy={records[-1][2].get('strategy')}")
    assert turn_progress > 0.06, diagnostic
    assert pose[2] > math.radians(10), diagnostic
    assert max_error < 0.035, diagnostic
