"""Odometry drift grid: prototypes A and B and the route_ab hybrid (H), same
injected error.

The comparison instrument (review 2026-09-23). lane_scenarios.run_scenario
renders the camera from the TRUE pose and scores the TRUE track; only the
pose handed to the follower is odometry (OdomError: (1+s) v, (1+s) w + bias
while moving, from the believed start). Every follower is built at the
believed start and runs under CORE's 3 s lease. Slow (360 closed-loop runs,
parallel over the host's cores): run with `-m drift`.

Acceptance (asserted):
  B   12/12 on every cell, moderate and severe; on the moderate grid the
      end estimate is within design §7's 20 mm of the truth.
  A   its measured capability after HIGH-1, below: at least the measured
      pass count on each moderate cell, and on the moderate grid every
      failure is fail-closed (CORE LOST after MANOEUVRE_ABORT), never a
      drive down the wrong branch. On the severe cells A is recorded, not
      asserted.
  H   12/12 on every moderate cell with the end estimate within 20 mm, and
      on every cell, severe included, no "unstopped" failure.

Measured on the Windows dev host, 2026-09-23 (the table the fixture prints;
71 s on 12 workers). Per cell: pass, max centre deviation mm, worst end
error of the follower's map pose mm, worst total stall s. A's failures are
"lost" (MANOEUVRE_ABORT, then CORE LOST) or "unstopped" (a wrong branch
driven on the camera until the step limit):

  cell                      A                                B
  none                      12/12  37.5    0.0 0.0           12/12  21.6   6.4 0.0
  3% scale                  12/12  35.4   23.7 0.0           12/12  21.5   6.8 0.0
  3% +0.01 rad/s            12/12  32.3   50.3 0.0           12/12  21.3   5.8 0.0
  3% -0.01 rad/s            10/12  59.0   60.6 3.2 (2 lost)  12/12  21.7   7.6 0.0
  start 20 mm / 2 deg       12/12  31.4   38.5 0.0           12/12  21.6   7.0 0.0
  3% +0.01, 20 mm / 2 deg    8/12 140.2  107.0 3.4 (4 lost)  12/12  21.8   5.7 0.0
  severe (A not asserted):
  5% +0.02 rad/s             5/12 152.4  861.6 3.4 (6 lost,  12/12  21.2  10.5 0.0
                                                 1 unstopped)
  5% -0.02 rad/s             6/12  87.4  514.7 3.4 (4 lost,  12/12  22.0  10.8 0.0
                                                 2 unstopped)
  start 30 mm / 3 deg        7/12  39.3   54.6 3.4 (5 lost)  12/12  24.4   6.4 0.2
  start -30 mm / -3 deg      5/12  81.5   57.5 3.4 (7 lost)  12/12  22.5   6.0 0.2

A's end error is its dead reckoning: nothing corrects its odometry (HIGH-3
is documented in route_camera, not redesigned). B's 0.2 s stalls are
single frames.

The hybrid H (route_hybrid), same host and date, 198 s for all 360 runs:

  cell                      H
  none                      12/12  37.5   6.8 0.0
  3% scale                  12/12  36.5   8.1 0.0
  3% +0.01 rad/s            12/12  32.2   8.2 0.0
  3% -0.01 rad/s            12/12  37.4   8.1 0.0
  start 20 mm / 2 deg       12/12  36.8   6.0 0.0
  3% +0.01, 20 mm / 2 deg   12/12  30.2   6.7 0.0
  severe:
  5% +0.02 rad/s            10/12  37.2  14.4 3.4 (2 lost)
  5% -0.02 rad/s            10/12  37.3  13.9 3.4 (2 lost)
  start 30 mm / 3 deg       12/12  36.2   6.5 0.2
  start -30 mm / -3 deg     12/12  39.1   6.4 0.2

Its four severe losses (01 and 10 at +0.02, 04 and 07 at -0.02 rad/s) are
all DISAGREE (camera path 26-28 mm off every centreline, over
MAX_DISAGREE_M) once the estimate lags the yaw bias; the robot then stands
still, the filter cannot move its position without motion, and CORE's
lease latches LOST. Fail-closed, never a wrong branch. H's deviation is
A's (its camera ring entries, 00 and 11), not B's.
"""

import math
import os
from multiprocessing import get_context

import pytest
from lane_scenarios import (
    GRAPH,
    SCENARIOS,
    OdomError,
    believed_start,
    run_scenario,
)

pytestmark = pytest.mark.drift

#: Design §7: B's end position, estimate against truth.
END_POSITION_MAX_ERROR_M = 0.020

MODERATE = {
    "none": OdomError(),
    "3% scale": OdomError(scale=0.03),
    "3% +0.01 rad/s": OdomError(scale=0.03, yaw_rate_bias=0.01),
    "3% -0.01 rad/s": OdomError(scale=0.03, yaw_rate_bias=-0.01),
    "start 20 mm / 2 deg": OdomError(start_offset_lateral_m=0.02,
                                     start_offset_yaw_rad=math.radians(2.0)),
    "3% +0.01, 20 mm / 2 deg": OdomError(0.03, 0.01, 0.02, math.radians(2.0)),
}
SEVERE = {
    "5% +0.02 rad/s": OdomError(scale=0.05, yaw_rate_bias=0.02),
    "5% -0.02 rad/s": OdomError(scale=0.05, yaw_rate_bias=-0.02),
    "start 30 mm / 3 deg": OdomError(start_offset_lateral_m=0.03,
                                     start_offset_yaw_rad=math.radians(3.0)),
    "start -30 mm / -3 deg": OdomError(start_offset_lateral_m=-0.03,
                                       start_offset_yaw_rad=math.radians(-3.0)),
}
CELLS = {**MODERATE, **SEVERE}

#: A's measured pass count after HIGH-1 (module docstring) on the moderate
#: cells, asserted as a floor.
A_MIN_PASS = {
    "none": 12,
    "3% scale": 12,
    "3% +0.01 rad/s": 12,
    "3% -0.01 rad/s": 10,
    "start 20 mm / 2 deg": 12,
    "3% +0.01, 20 mm / 2 deg": 8,
}


def run_one(kind, cell, index):
    """One closed-loop run (module level, so a worker process can run it)."""
    import lane_sim
    from control.sensing.route_camera import RouteCameraFollower
    from control.sensing.route_hybrid import RouteHybridFollower
    from control.sensing.route_map import RouteMapFollower

    scenario = SCENARIOS[index]
    error = CELLS[cell]
    keys = [scenario["into"], scenario["out"]]
    start = believed_start(scenario, error)
    if kind == "A":
        follower = RouteCameraFollower(GRAPH, keys, start_pose=start,
                                       camera_x_offset_m=lane_sim.CAM_X)
    elif kind == "B":
        follower = RouteMapFollower(GRAPH, keys, start_pose=start,
                                    camera_x_offset_m=lane_sim.CAM_X, seed=7)
    else:
        follower = RouteHybridFollower(GRAPH, keys, start_pose=start,
                                       camera_x_offset_m=lane_sim.CAM_X, seed=7)
    result = run_scenario(scenario, follower, steps=260, odom_error=error)
    if kind == "A":
        estimate = follower.map_pose
    else:
        last = follower.last.get("estimate")
        estimate = None if last is None else last.pose
    end_error = (math.inf if estimate is None
                 else math.dist(estimate[:2], result["last_true_pose"][:2]))
    return {
        "kind": kind, "cell": cell, "index": index, "pass": bool(result["pass"]),
        "lost": result["reason"] == "lost", "dev": float(result["max_centre_dev_m"]),
        "end_error": end_error, "stall_s": result["stall_s"],
        "max_stall_s": result["max_stall_s"], "last_tier": result["tiers"][-1],
    }


def _row(runs):
    passed = sum(r["pass"] for r in runs)
    lost = sum(r["lost"] for r in runs)
    unstopped = sum(not r["pass"] and not r["lost"] for r in runs)
    return (f"{passed:2d}/{len(runs)}  dev {max(r['dev'] for r in runs) * 1000:5.1f} mm"
            f"  end {max(r['end_error'] for r in runs) * 1000:5.1f} mm"
            f"  stall {max(r['stall_s'] for r in runs):3.1f} s"
            f"  (lost {lost}, unstopped {unstopped})")


@pytest.fixture(scope="module")
def grid(request):
    jobs = [(kind, cell, index) for kind in "ABH" for cell in CELLS for index in range(12)]
    with get_context("spawn").Pool(min(12, os.cpu_count() or 1)) as pool:
        runs = pool.starmap(run_one, jobs, chunksize=1)
    table = {(kind, cell): [r for r in runs if r["kind"] == kind and r["cell"] == cell]
             for kind in "ABH" for cell in CELLS}
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    lines = ["", "drift grid: pass, max centre dev, worst end error, worst total stall"]
    for cell in CELLS:
        lines.append(f"  {cell:<24} A {_row(table['A', cell])}")
        lines.append(f"  {'':<24} B {_row(table['B', cell])}")
        lines.append(f"  {'':<24} H {_row(table['H', cell])}")
    for line in lines:
        if reporter is not None:
            reporter.write_line(line)
        else:
            print(line)
    return table


@pytest.mark.parametrize("cell", list(CELLS))
def test_b_drives_every_cell(grid, cell):
    runs = grid["B", cell]
    assert all(r["pass"] for r in runs), _row(runs)
    if cell in MODERATE:
        worst = max(r["end_error"] for r in runs)
        assert worst <= END_POSITION_MAX_ERROR_M, (worst, _row(runs))


@pytest.mark.parametrize("cell", list(MODERATE))
def test_a_keeps_its_measured_capability(grid, cell):
    runs = grid["A", cell]
    assert sum(r["pass"] for r in runs) >= A_MIN_PASS[cell], _row(runs)
    unstopped = [r["index"] for r in runs if not r["pass"] and not r["lost"]]
    assert not unstopped, (unstopped, _row(runs))


@pytest.mark.parametrize("cell", list(MODERATE))
def test_hybrid_drives_every_moderate_cell(grid, cell):
    runs = grid["H", cell]
    assert all(r["pass"] for r in runs), _row(runs)
    worst = max(r["end_error"] for r in runs)
    assert worst <= END_POSITION_MAX_ERROR_M, (worst, _row(runs))


@pytest.mark.parametrize("cell", list(CELLS))
def test_hybrid_never_drives_on_unstopped(grid, cell):
    runs = grid["H", cell]
    unstopped = [r["index"] for r in runs if not r["pass"] and not r["lost"]]
    assert not unstopped, (unstopped, _row(runs))
