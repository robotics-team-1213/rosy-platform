"""All-lane tour, offline closed loop (mission plan stage 2, step 3).

lane_coverage's tour from the parking junction on west back to it, driven
by the route_ab hybrid under lane_scenarios.run_route (the junction
scenarios' renderer, CORE law and 3 s lease) and scored with
junction_score.score_route, over TOUR_SEEDS (the localiser's random
draws). Measured on the Windows dev host, 2026-09-23, with the
localiser's along-track noise at MOTION_ALONG_SIGMA_PER_M (0.10): every
seed passes, 1622-1637 steps, max centre deviation 22.5-23.4 mm, end
1.4-14.1 mm from the start, no stop. At the old isotropic 0.20 seed 3
stopped on SPREAD on east:r (CORE LOST at 4.03 m of 16.87).

Drift cells (`-m drift`, lane_scenarios.OdomError, follower built at the
believed start) at DRIFT_SEEDS, same host and day. Stops: frames entering
STOP / LOCALISE_STOP / MANOEUVRE_ABORT; est: the follower's end estimate
against the truth.

  cell                  seed  pass  dev mm  stops  stall s (max)  end mm  est mm
  none                    3   PASS   22.9     0    0.0 (0.0)      12.8     0.6
  none                    7   PASS   22.8     0    0.0 (0.0)       1.4     2.4
  3% scale                3   PASS   22.4     0    0.0 (0.0)       9.7    11.0
  3% scale                7   PASS   22.5     0    0.0 (0.0)       3.3    11.5
  3% +0.01 rad/s          3   PASS   27.4     4    0.8 (0.2)       8.0     8.4
  3% +0.01 rad/s          7   PASS   26.4     0    0.0 (0.0)       3.4     9.4
  3% -0.01 rad/s          3   PASS   24.0     0    0.0 (0.0)      15.1    12.0
  3% -0.01 rad/s          7   PASS   24.0     0    0.0 (0.0)       8.6    11.5
  start 20 mm / 2 deg     3   PASS   23.0     0    0.0 (0.0)      12.2     1.0
  start 20 mm / 2 deg     7   PASS   23.7     0    0.0 (0.0)       1.8     1.6
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
#: ONE (0.69 speed) and MEMORY slow it. 1622-1637 were measured.
MAX_STEPS = 2600


#: Localiser seeds for the clean tour. The filter's random draws decide
#: its spread on the long corridors, so one seed is not the evidence.
TOUR_SEEDS = (1, 2, 3, 4, 5, 7, 11)


def tour_follower(start=POSE, seed=7):
    return RouteHybridFollower(GRAPH, KEYS, start_pose=start,
                               camera_x_offset_m=lane_sim.CAM_X, seed=seed)


def _stops(tiers):
    return sum(1 for a, b in zip(["-"] + tiers, tiers)
               if b in ("STOP", "LOCALISE_STOP", "MANOEUVRE_ABORT")
               and a not in ("STOP", "LOCALISE_STOP", "MANOEUVRE_ABORT"))


def run_clean_seed(seed):
    """One clean tour (module level, so a worker process can run it)."""
    r = run_route(KEYS, POSE, tour_follower(seed=seed), MAX_STEPS)
    return {"seed": seed, "stops": _stops(r["tiers"]),
            **{k: v for k, v in r.items()
               if k not in ("track", "tiers", "last_true_pose", "last_odom_pose")}}


def _pool_map(fn, jobs):
    import os
    from multiprocessing import get_context
    with get_context("spawn").Pool(min(len(jobs), os.cpu_count() or 1)) as pool:
        return pool.map(fn, jobs, chunksize=1)


def _report(request, lines):
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    for line in lines:
        if reporter is not None:
            reporter.write_line(line)
        else:
            print(line)


@pytest.fixture(scope="module")
def clean(request):
    runs = _pool_map(run_clean_seed, list(TOUR_SEEDS))
    _report(request, ["", ("clean tour per localiser seed: pass, max centre dev, "
                           "end distance, stops, max stall, steps")]
            + [(f"  seed {r['seed']:>2} {'PASS' if r['pass'] else 'FAIL'}"
                f"  dev {r['max_centre_dev_m'] * 1000:5.1f} mm"
                f"  end {r['end_distance_m'] * 1000:6.1f} mm  stops {r['stops']}"
                f"  stall {r['max_stall_s']:.1f} s  steps {r['steps']}"
                f"  {r['reason'] or ''} {r['missing'] or ''}") for r in runs])
    return {r["seed"]: r for r in runs}


@pytest.mark.parametrize("seed", TOUR_SEEDS)
def test_the_hybrid_drives_the_whole_tour_on_clean_odometry(clean, seed):
    r = clean[seed]
    assert r["pass"], r
    assert r["missing"] == [] and all(r["segments_driven"]), r
    assert not r["wrong_way"] and not r["wrong_branch"], r
    assert r["ring_ccw_ok"], r
    assert r["max_centre_dev_m"] <= 0.040, r
    assert r["reason"] is None and r["max_stall_s"] < 3.0, r
    assert r["end_distance_m"] <= 0.05, r


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


#: Localiser seeds for the drift cells.
DRIFT_SEEDS = (3, 7)


def run_tour_cell(job):
    """One drift cell at one localiser seed (module level, so a worker
    process can run it)."""
    import math

    from lane_scenarios import OdomError, believed_start
    cell, seed = job
    error = OdomError(**TOUR_CELLS[cell])
    follower = tour_follower(believed_start({"start": POSE}, error), seed=seed)
    r = run_route(KEYS, POSE, follower, MAX_STEPS, odom_error=error)
    estimate = follower.last.get("estimate")
    return {"cell": cell, "seed": seed, "pass": bool(r["pass"]), "dev": r["max_centre_dev_m"],
            "end": r["end_distance_m"], "reason": r["reason"],
            "stall_s": r["stall_s"], "max_stall_s": r["max_stall_s"],
            "stops": _stops(r["tiers"]), "missing": r["missing"], "steps": r["steps"],
            "estimate_error": (math.inf if estimate is None
                               else math.dist(estimate.pose[:2], r["last_true_pose"][:2]))}


@pytest.fixture(scope="module")
def drift_cells(request):
    runs = _pool_map(run_tour_cell, [(c, s) for c in TOUR_CELLS for s in DRIFT_SEEDS])
    _report(request, ["", ("tour drift cells: seed, pass, max centre dev, stops, stall, "
                           "end distance, estimate error, steps")]
            + [(f"  {r['cell']:<22} seed {r['seed']:>2} {'PASS' if r['pass'] else 'FAIL'}"
                f"  dev {r['dev'] * 1000:5.1f} mm  stops {r['stops']}"
                f"  stall {r['stall_s']:.1f} s (max {r['max_stall_s']:.1f})"
                f"  end {r['end'] * 1000:5.1f} mm"
                f"  est {r['estimate_error'] * 1000:5.1f} mm  steps {r['steps']}"
                f"  {r['reason'] or ''} {r['missing'] or ''}") for r in runs])
    return {(r["cell"], r["seed"]): r for r in runs}


@pytest.mark.drift
@pytest.mark.parametrize("seed", DRIFT_SEEDS)
@pytest.mark.parametrize("cell", list(TOUR_CELLS))
def test_the_tour_survives_odometry_drift(drift_cells, cell, seed):
    r = drift_cells[(cell, seed)]
    assert r["pass"], r
    assert r["reason"] is None and r["dev"] <= 0.040 and r["end"] <= 0.05, r
