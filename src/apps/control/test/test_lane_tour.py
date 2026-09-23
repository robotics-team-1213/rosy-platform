"""All-lane tour, offline closed loop (mission plan stage 2, step 3).

lane_coverage's tour from the parking junction on west back to it, driven
by the route_ab hybrid under lane_scenarios.run_route (the junction
scenarios' renderer, CORE law and 3 s lease) and scored with
junction_score.score_route. Measured on the Windows dev host, 2026-09-23:
1694 steps (339 s sim), max centre deviation 23.1 mm, no stall, end 7 mm
from the start.
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
