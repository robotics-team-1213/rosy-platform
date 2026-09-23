"""Hybrid route_ab: B's paint-localised pose steering A's camera-first follower."""

import copy
import dataclasses
import math

import cv2
import lane_sim
import numpy as np
import pytest
from control.sensing.lane_bev import MEMORY_CONFIDENCE
from control.sensing.route_hybrid import RouteHybridFollower, ring_entries
from control.sensing.route_map import MAX_SPREAD_M, MIN_MATCH, confidence_for
from lane_scenarios import (
    GRAPH,
    SCENARIOS,
    WORLD,
    junction_score,
    run_scenario,
    summary,
)
from lane_sim import CAM_X

#: Design §7: end position, estimate against truth.
END_POSITION_MAX_ERROR_M = 0.020


def follower(scenario, start=None):
    return RouteHybridFollower(GRAPH, [scenario["into"], scenario["out"]],
                               start_pose=scenario["start"] if start is None else start,
                               camera_x_offset_m=CAM_X, seed=7)


def _world_without_paint_after_the_node(scenario):
    """WORLD with every painted pixel within 0.25 m of `out`'s centreline
    past its first 0.10 m erased (test_route_map's fail-closed world)."""
    world = copy.copy(WORLD)
    world.paint = WORLD.paint.copy()
    out = junction_score.directed_points(GRAPH, scenario["out"])
    after = out[junction_score._arc_length(out) >= 0.10]
    mask = np.zeros_like(world.paint)
    pts = np.rint(world.px(after) * 16).astype(np.int32)
    cv2.polylines(mask, [pts], False, 255, 500, shift=4)
    world.paint[mask > 0] = 0
    return world


@pytest.mark.parametrize("index", range(12))
def test_every_junction_transition_is_driven(index):
    scenario = SCENARIOS[index]
    f = follower(scenario)
    result = run_scenario(scenario, f, steps=260)
    result["scenario"] = scenario
    assert result["reached_end"], summary([result])
    assert result["branch_ok"], summary([result])
    assert not result["wrong_way"], summary([result])
    assert result["ring_ccw_ok"], summary([result])
    assert result["max_centre_dev_m"] <= 0.040, summary([result])
    assert result["reason"] is None
    error = math.dist(f.last["estimate"].pose[:2], result["last_true_pose"][:2])
    assert error <= END_POSITION_MAX_ERROR_M, (error, summary([result]))


#: Road-to-ring entries among the 12 scenarios (00 and 11 are the two
#: Gazebo failures, 2026-09-23 comparison.md).
RING_ENTRIES = (0, 5, 6, 11)
#: Offline bound on a ring entry: the target set for the fix (measured
#: 22.1 / 13.3 / 21.8 / 21.3 mm; A's camera steering read 37.5 / 20.9 /
#: 30.7 / 37.3 mm).
RING_ENTRY_MAX_DEV_M = 0.025


def test_ring_entries_are_the_road_to_ring_nodes():
    flagged = [i for i, sc in enumerate(SCENARIOS)
               if ring_entries(GRAPH, [sc["into"], sc["out"]])[0]]
    assert flagged == list(RING_ENTRIES)
    assert ring_entries({**GRAPH, "roundabout": None}, ["east:r", "ring_n:f"]) == [False]


class _SteerLog:
    def __init__(self, subject):
        self.subject = subject
        self.steer = []

    @property
    def state(self):
        return self.subject.state

    def update(self, *args, **kwargs):
        out = self.subject.update(*args, **kwargs)
        if out is not None:
            self.steer.append(self.subject.last["steer"])
        return out


@pytest.mark.parametrize("index", RING_ENTRIES)
def test_a_ring_entry_is_steered_on_the_route(index):
    """Road to ring, A's camera target lies on the centreline but its 0.15 m
    pursuit dips into the island (route_hybrid docstring); B's 0.12 m route
    pursuit steers within JUNCTION_ARM_M of the node."""
    scenario = SCENARIOS[index]
    log = _SteerLog(follower(scenario))
    result = run_scenario(scenario, log, steps=260)
    result["scenario"] = scenario
    assert result["pass"], summary([result])
    assert result["max_centre_dev_m"] <= RING_ENTRY_MAX_DEV_M, summary([result])
    assert "route" in log.steer


@pytest.mark.parametrize("index", sorted(set(range(12)) - set(RING_ENTRIES)))
def test_elsewhere_the_camera_steers(index):
    """Ring exits and ring to ring stay A's (camera, or its own manoeuvre):
    route pursuit on the NE exit (01) read 10.7 mm against the camera's 3.8."""
    scenario = SCENARIOS[index]
    log = _SteerLog(follower(scenario))
    run_scenario(scenario, log, steps=260)
    assert set(log.steer) <= {"camera", "manoeuvre"}
    assert "camera" in log.steer


class _OdomFrameAtOrigin:
    """Odometry whose frame starts at (0, 0, 0) while the robot stands at the
    scenario start (a real /odom, unlike Gazebo's)."""

    def __init__(self, subject, start):
        self.subject = subject
        self._start = tuple(float(v) for v in start)

    @property
    def state(self):
        return self.subject.state

    def update(self, now_s, pose, bgr, ground, **kwargs):
        x0, y0, yaw0 = self._start
        c, s = math.cos(yaw0), math.sin(yaw0)
        dx, dy = pose[0] - x0, pose[1] - y0
        odom = (c * dx + s * dy, -s * dx + c * dy, pose[2] - yaw0)
        return self.subject.update(now_s, odom, bgr, ground, **kwargs)


@pytest.mark.parametrize("index", [0, 5, 7, 11])
def test_odometry_from_its_own_origin_is_placed_on_the_map(index):
    """/odom starts at (0, 0, 0) wherever the robot is: the localiser uses
    odometry increments only, so the map pose is still right."""
    scenario = SCENARIOS[index]
    subject = follower(scenario)
    result = run_scenario(scenario, _OdomFrameAtOrigin(subject, scenario["start"]), steps=260)
    result["scenario"] = scenario
    assert result["pass"], summary([result])
    assert result["max_centre_dev_m"] <= 0.040, summary([result])
    error = math.dist(subject.map_pose[:2], result["last_true_pose"][:2])
    assert error <= END_POSITION_MAX_ERROR_M, error


def test_paint_erased_after_the_node_stops_the_follower():
    """Fail-closed: the robot reaches the node on real paint, then looks at
    bare floor. The localiser's match collapses (or A's manoeuvre aborts):
    no output, never a blind drive to the end."""
    scenario = SCENARIOS[5]
    f = follower(scenario)
    result = run_scenario(scenario, f, steps=260,
                          world=_world_without_paint_after_the_node(scenario))
    assert not result["pass"]
    assert not result["reached_end"]
    assert result["reason"] == "lost"
    assert result["tiers"][-1] in ("LOCALISE_STOP", "MANOEUVRE_ABORT", "STOP")


def test_a_diverged_localiser_stops_the_follower():
    """Fail-closed: a particle cloud blown past MAX_SPREAD_M (a kidnap, a
    slip the filter cannot follow) is no output, reason SPREAD, whatever
    the camera still sees."""
    scenario = SCENARIOS[5]
    f = follower(scenario)
    pose = tuple(scenario["start"])
    frame = WORLD.render(pose)
    for k in range(3):
        assert f.update(k * lane_sim.DT, pose, frame, lane_sim.GROUND, **lane_sim.KW) is not None
    particles = f._localizer._particles
    particles[:, :2] += np.random.default_rng(1).normal(0.0, 0.08, (len(particles), 2))
    observation = f.update(3 * lane_sim.DT, pose, frame, lane_sim.GROUND, **lane_sim.KW)
    assert observation is None
    assert f.state == "LOCALISE_STOP"
    assert f.last["reason"] in ("SPREAD", "MATCH")
    assert f.last["estimate"].spread_m > MAX_SPREAD_M or f.last["estimate"].match < MIN_MATCH


def _biased(f, offset_m):
    """Test double: every estimate is shifted `offset_m` to its left
    (negative: right), as a localiser locked onto the wrong paint would be."""
    update = f._localizer.update

    def biased(*args, **kwargs):
        estimate = update(*args, **kwargs)
        if estimate is None:
            return None
        x, y, yaw = estimate.pose
        return dataclasses.replace(estimate, pose=(x - offset_m * math.sin(yaw),
                                                   y + offset_m * math.cos(yaw), yaw))

    f._localizer.update = biased
    return f


@pytest.mark.parametrize(("index", "offset_m"),
                         [(0, -0.05), (6, -0.05), (0, -0.03), (11, -0.03)])
def test_a_biased_estimate_is_not_driven_off_the_lane(index, offset_m):
    """Why B's camera/route disagreement check is kept. Measured 2026-09-23
    over the 12 scenarios with the estimate shifted +-30 / +-50 mm (48 runs):
    without the check 29 passed (the camera keeps the lane between nodes),
    13 stopped, and 6 drove to the end on the right branch 43-63 mm off the
    centreline without stopping (these four among them); with it 47 stop
    (39 DISAGREE, 8 A's own STOP) and one passes (04, +30 mm, 14 mm), none
    unstopped. The cost: an estimate 30 mm off stops the robot where the
    camera alone would often have coped."""
    scenario = SCENARIOS[index]
    f = _biased(follower(scenario), offset_m)
    result = run_scenario(scenario, f, steps=260)
    result["scenario"] = scenario
    assert not result["pass"], summary([result])
    assert result["reason"] == "lost", summary([result])
    assert f.last["reason"] == "DISAGREE", f.last["reason"]


def test_without_odometry_or_ground_there_is_no_output():
    scenario = SCENARIOS[5]
    frame = WORLD.render(scenario["start"])
    f = follower(scenario)
    assert f.update(0.0, None, frame, lane_sim.GROUND, **lane_sim.KW) is None
    assert f.state == "LOCALISE_STOP"
    assert f.last["reason"] == "NO_ESTIMATE"
    f = follower(scenario)
    assert f.update(0.0, scenario["start"], frame, None, **lane_sim.KW) is None
    assert f.last["reason"] == "NO_ESTIMATE"


def test_confidence_is_the_weaker_of_camera_and_localisation():
    """A weak localisation slows CORE too: the output confidence never
    exceeds B's estimate-quality confidence."""
    scenario = SCENARIOS[0]
    f = follower(scenario)
    pose = tuple(scenario["start"])
    for k in range(10):
        obs = f.update(k * lane_sim.DT, pose, WORLD.render(pose), lane_sim.GROUND, **lane_sim.KW)
        if obs is None:
            continue
        estimate = f.last["estimate"]
        assert 0.35 < obs.confidence <= confidence_for(estimate.match, estimate.spread_m) + 1e-9
        assert obs.confidence <= f.last["camera_confidence"] + 1e-9


def test_a_lower_confidence_keeps_the_commanded_curvature():
    """CORE's error encodes curvature at the output confidence (lane_bev
    error_for_curvature). Lowering the confidence re-encodes the error so
    the path curvature v / w is unchanged; only the speed drops."""
    from control.sensing.lane import LaneObservation
    from control.sensing.lane_bev import error_for_curvature
    from control.sensing.route_hybrid import _with_confidence

    for curvature in (-8.0, -1.0, 0.0, 2.5, 9.0):
        obs = LaneObservation(error=error_for_curvature(curvature, 0.9), confidence=0.9)
        slower = _with_confidence(obs, MEMORY_CONFIDENCE)
        assert slower.confidence == MEMORY_CONFIDENCE
        assert slower.error == pytest.approx(error_for_curvature(curvature, MEMORY_CONFIDENCE))
        v, w = lane_sim.core_command(slower)
        if curvature:
            assert w / v == pytest.approx(curvature, rel=1e-6)
    obs = LaneObservation(error=0.2, confidence=0.5)
    assert _with_confidence(obs, 0.9) is obs      # never raised


def test_last_exposes_the_tracker_and_the_estimate_for_the_overlay():
    scenario = SCENARIOS[5]
    f = follower(scenario)
    pose = tuple(scenario["start"])
    f.update(0.0, pose, WORLD.render(pose), lane_sim.GROUND, **lane_sim.KW)
    last = f.last
    assert last["estimate"] is not None
    assert {"spread_m", "match"} <= set(last)
    tracker = last["tracker"]
    assert tracker.get("paint") is not None
    assert {"memory", "right_memory", "target"} <= set(tracker)
    assert f.view is not None


def test_the_camera_tracker_keeps_its_boundary_memory_on_odometry():
    """The route (seed, select, manoeuvre) is placed by the estimate, but the
    tracker's boundary memory is carried by odometry: smooth frame to frame,
    where the estimate steps on every resample. Measured over seeds 7/1/2 on
    the moderate cell 3% +0.01 rad/s, 20 mm / 2 deg: estimate-carried memory
    drove 00 to 43.0 / 35.7 / 43.0 mm (two over the 40 mm bound), odometry-
    carried 30.2 / 30.2 / 30.7 mm; clean runs are within 1 mm either way."""
    scenario = SCENARIOS[5]
    f = follower(scenario)
    seen = []
    tracker = f._follower._tracker
    update = tracker.update

    def spy(now_s, pose, *args, **kwargs):
        seen.append(pose)
        return update(now_s, pose, *args, **kwargs)

    tracker.update = spy
    x, y, yaw = scenario["start"]
    odom = (x + 0.004, y - 0.003, yaw)       # odometry a few mm off the map pose
    f.update(0.0, odom, WORLD.render(scenario["start"]), lane_sim.GROUND, **lane_sim.KW)
    assert seen == [pytest.approx(odom)]
    assert f.map_pose != pytest.approx(odom)


def test_the_route_forbids_the_wrong_way_round_the_ring():
    with pytest.raises(ValueError, match="one-way"):
        RouteHybridFollower(GRAPH, ["west:f", "ring_n:r"], start_pose=(0, 0, 0),
                            camera_x_offset_m=CAM_X)
