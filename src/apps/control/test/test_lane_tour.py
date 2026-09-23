"""All-lane tour, offline closed loop (mission plan stage 2, step 3).

lane_coverage's tour from the parking junction on west back to it, driven
by the route_ab hybrid under lane_scenarios.run_route (the junction
scenarios' renderer, CORE law and 3 s lease) and scored with
junction_score.score_route. Measured on the Windows dev host, 2026-09-23:
1694 steps (339 s sim), max centre deviation 23.1 mm, no stall, end 7 mm
from the start.

Drift cells (`-m drift`, lane_scenarios.OdomError, follower built at the
believed start), same host and day. Stops: frames entering STOP /
LOCALISE_STOP / MANOEUVRE_ABORT; est: the follower's end estimate against
the truth.

  cell                   pass  dev mm  stops  stall s (max)  end mm  est mm
  none                   PASS   23.1     0    0.0 (0.0)       7.2     2.3
  3% scale               PASS   22.3     0    0.0 (0.0)      12.2     6.3
  3% +0.01 rad/s         PASS   27.7     5    1.2 (0.4)      14.5     6.2
  3% -0.01 rad/s         PASS   23.5     0    0.0 (0.0)      13.5    11.5
  start 20 mm / 2 deg    PASS   22.9     0    0.0 (0.0)       1.2     2.1
"""

import lane_sim
import numpy as np
import pytest
from control.sensing.lane_coverage import coverage_route, tour_start_pose
from control.sensing.route_hybrid import (
    BEND_TURN_RAD,
    RouteHybridFollower,
    road_bends,
)
from lane_scenarios import GRAPH, run_route

START = tuple(GRAPH["parking"]["points"][0])
KEYS = coverage_route(GRAPH, START)
POSE = tour_start_pose(GRAPH, KEYS, START)
#: 16.874 m at CORE's 0.08 m/s cruise is 1055 steps of 0.2 s; bends,
#: ONE (0.69 speed) and MEMORY slow it. 1694 were measured.
MAX_STEPS = 2600


def tour_follower(start=POSE):
    return RouteHybridFollower(GRAPH, KEYS, start_pose=start,
                               camera_x_offset_m=lane_sim.CAM_X, seed=7)


@pytest.fixture(scope="module")
def clean():
    follower = tour_follower()
    result = run_route(KEYS, POSE, follower, MAX_STEPS)
    result["follower"] = follower
    return result


def _brief(r):
    return {k: v for k, v in r.items()
            if k not in ("track", "tiers", "follower", "last_true_pose", "last_odom_pose")}


def test_the_hybrid_drives_the_whole_tour_on_clean_odometry(clean):
    assert clean["pass"], _brief(clean)
    assert clean["missing"] == [] and all(clean["segments_driven"]), _brief(clean)
    assert not clean["wrong_way"] and not clean["wrong_branch"], _brief(clean)
    assert clean["ring_ccw_ok"], _brief(clean)
    assert clean["max_centre_dev_m"] <= 0.040, _brief(clean)
    assert clean["reason"] is None and clean["max_stall_s"] < 3.0, _brief(clean)
    assert clean["end_distance_m"] <= 0.05, _brief(clean)


def test_road_bends_lie_on_roads_only():
    f = tour_follower()._follower
    bends = road_bends(GRAPH, KEYS, f._points, f._arc, f._seg_start)
    assert len(bends)
    segment = np.searchsorted(f._seg_start, bends, side="right") - 1
    assert all(not KEYS[i].startswith("ring") for i in segment)
    # Every ring arc turns 22.8 deg per 0.1 m, over the threshold: excluded
    # by segment, not by curvature.
    assert np.degrees(0.1 / GRAPH["roundabout"]["radius"]) > np.degrees(BEND_TURN_RAD)


# --- Odometry drift (step 4): run with -m drift ------------------------------

TOUR_CELLS = {
    "none": {},
    "3% scale": {"scale": 0.03},
    "3% +0.01 rad/s": {"scale": 0.03, "yaw_rate_bias": 0.01},
    "3% -0.01 rad/s": {"scale": 0.03, "yaw_rate_bias": -0.01},
    "start 20 mm / 2 deg": {"start_offset_lateral_m": 0.02,
                            "start_offset_yaw_rad": float(np.radians(2.0))},
}


def run_tour_cell(cell):
    """One drift cell (module level, so a worker process can run it)."""
    import math

    from lane_scenarios import OdomError, believed_start
    error = OdomError(**TOUR_CELLS[cell])
    follower = tour_follower(believed_start({"start": POSE}, error))
    r = run_route(KEYS, POSE, follower, MAX_STEPS, odom_error=error)
    estimate = follower.last.get("estimate")
    return {"cell": cell, "pass": bool(r["pass"]), "dev": r["max_centre_dev_m"],
            "end": r["end_distance_m"], "reason": r["reason"],
            "stall_s": r["stall_s"], "max_stall_s": r["max_stall_s"],
            "stops": sum(1 for a, b in zip(["-"] + r["tiers"], r["tiers"])
                         if b in ("STOP", "LOCALISE_STOP", "MANOEUVRE_ABORT")
                         and a not in ("STOP", "LOCALISE_STOP", "MANOEUVRE_ABORT")),
            "missing": r["missing"], "steps": r["steps"],
            "estimate_error": (math.inf if estimate is None
                               else math.dist(estimate.pose[:2], r["last_true_pose"][:2]))}


@pytest.fixture(scope="module")
def drift_cells(request):
    import os
    from multiprocessing import get_context
    with get_context("spawn").Pool(min(len(TOUR_CELLS), os.cpu_count() or 1)) as pool:
        runs = pool.map(run_tour_cell, list(TOUR_CELLS), chunksize=1)
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    lines = ["", "tour drift cells: pass, max centre dev, stops, stall, end distance, "
                 "estimate error, steps"]
    for r in runs:
        lines.append(f"  {r['cell']:<22} {'PASS' if r['pass'] else 'FAIL'}"
                     f"  dev {r['dev'] * 1000:5.1f} mm  stops {r['stops']}"
                     f"  stall {r['stall_s']:.1f} s (max {r['max_stall_s']:.1f})"
                     f"  end {r['end'] * 1000:5.1f} mm"
                     f"  est {r['estimate_error'] * 1000:5.1f} mm  steps {r['steps']}"
                     f"  {r['reason'] or ''} {r['missing'] or ''}")
    for line in lines:
        if reporter is not None:
            reporter.write_line(line)
        else:
            print(line)
    return {r["cell"]: r for r in runs}


@pytest.mark.drift
@pytest.mark.parametrize("cell", list(TOUR_CELLS))
def test_the_tour_survives_odometry_drift(drift_cells, cell):
    r = drift_cells[cell]
    assert r["pass"], r
    assert r["reason"] is None and r["dev"] <= 0.040 and r["end"] <= 0.05, r
