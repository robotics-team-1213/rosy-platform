"""Offline closed loop for the 12 junction scenarios (test helper).

Same three parts as the Gazebo harness, minus Gazebo: lane_sim renders the
STL paint through the declared camera, CORE's law turns an observation into
a command, and junction_score judges the resulting track (direction-aware).
A follower here is anything with `.update(now_s, pose, bgr, ground, **KW)`
returning a LaneObservation or None, like LaneBoundaryTracker.

Two additions over the harness, both on by construction of the loop:

  odometry  `odom_error` (OdomError) corrupts ONLY the pose handed to the
            follower: odometry starts at `believed_start` (start (+) the
            offset; build the follower with it as its start pose too: a
            robot set down off its mark does not know it) and integrates
            (1 + scale) v and (1 + scale) w + yaw_rate_bias (the bias only
            while commanded to move). The camera renders the true pose and
            the score uses the true track.
  lease     CORE line_follow's loss timer: evidence that is None or under
            CORE_MIN_CONFIDENCE for longer than LOST_AFTER_S (CORE's
            lost_after_s) latches LOST, and the run ends with reason "lost".
            `stall_s` is the total time without valid evidence, `max_stall_s`
            the longest stretch.
"""

import importlib.util
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

import lane_sim

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = ROOT / "map" / "map_v2_fleet" / "lane_graph.yaml"
SCORE_PATH = ROOT.parents[1] / "sim" / "gz_sim" / "scripts" / "junction_score.py"


def _junction_score():
    spec = importlib.util.spec_from_file_location("junction_score", SCORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


junction_score = _junction_score()
GRAPH = yaml.safe_load(GRAPH_PATH.read_text(encoding="utf-8"))
SCENARIOS = junction_score.scenarios(GRAPH)
WORLD = lane_sim.stl_world()
#: The tour's world: WORLD without the perimeter wall's base (lane_sim.
#: stl_world). The tour drives the east corridor 0.08 m from that wall:
#: in WORLD its 5 mm base shows as a paint line that PaintLocalizer's map
#: (and Gazebo, where the wall stands on it) does not have, and the paint
#: match fell 0.66 -> 0.17 in one frame (LOCALISE_STOP MATCH, then LOST).
TOUR_WORLD = lane_sim.stl_world(wall_footprint=False)

#: CORE line_follow defaults (LineFollowConfig): evidence under
#: min_confidence, or none, for longer than lost_after_s latches LOST.
CORE_MIN_CONFIDENCE = 0.35
LOST_AFTER_S = 3.0


@dataclass(frozen=True)
class OdomError:
    """Odometry error injected by `run_scenario` (see the module docstring).
    The start offset is in the start pose's frame: lateral is to its left."""

    scale: float = 0.0
    yaw_rate_bias: float = 0.0
    start_offset_lateral_m: float = 0.0
    start_offset_yaw_rad: float = 0.0


def believed_start(scenario, odom_error=None):
    """Where the robot thinks it starts: the scenario start (+) the offset."""
    x, y, yaw = (float(v) for v in scenario["start"])
    if odom_error is None:
        return (x, y, yaw)
    lateral = odom_error.start_offset_lateral_m
    return (x - lateral * math.sin(yaw), y + lateral * math.cos(yaw),
            yaw + odom_error.start_offset_yaw_rad)


def _integrate(pose, linear, angular):
    mid = pose[2] + angular * lane_sim.DT / 2.0
    return (pose[0] + linear * lane_sim.DT * math.cos(mid),
            pose[1] + linear * lane_sim.DT * math.sin(mid),
            pose[2] + angular * lane_sim.DT)


def run_scenario(scenario, follower, *, steps=200, world=None, odom_error=None):
    """Drive one scenario offline; return the score plus the track, tiers,
    final and last-seen poses, the lease outcome (`reason`: "lost" or None)
    and the stall times."""
    world = WORLD if world is None else world
    error = OdomError() if odom_error is None else odom_error
    pose = tuple(scenario["start"])
    odom = believed_start(scenario, error)
    track, tiers = [pose[:2]], []
    end = junction_score.directed_points(GRAPH, scenario["out"])
    end_s = junction_score._arc_length(end)
    end_point = end[int(end_s.searchsorted(junction_score.END_AFTER_M))]
    reason, loss_started, stall, stretch, max_stretch = None, None, 0, 0, 0
    last_true, last_odom = pose, odom
    for step in range(steps):
        now = step * lane_sim.DT
        last_true, last_odom = pose, odom
        observation = follower.update(now, odom, world.render(pose),
                                      lane_sim.GROUND, **lane_sim.KW)
        tiers.append(getattr(follower, "state", "-"))
        if observation is None or observation.confidence < CORE_MIN_CONFIDENCE:
            stall += 1
            stretch += 1
            max_stretch = max(max_stretch, stretch)
            loss_started = now if loss_started is None else loss_started
            if now - loss_started > LOST_AFTER_S:
                reason = "lost"
                break
        else:
            loss_started, stretch = None, 0
        linear, angular = lane_sim.core_command(observation)
        pose = _integrate(pose, linear, angular)
        moving = linear > 0.0 or angular != 0.0
        odom = _integrate(odom, (1.0 + error.scale) * linear,
                          (1.0 + error.scale) * angular
                          + (error.yaw_rate_bias if moving else 0.0))
        track.append(pose[:2])
        if math.dist(pose[:2], end_point) < 0.05:
            break
    result = junction_score.score(GRAPH, scenario, track)
    if reason is not None:
        result["pass"] = False
    result.update(track=track, tiers=tiers, final_pose=pose, reason=reason,
                  stall_s=stall * lane_sim.DT, max_stall_s=max_stretch * lane_sim.DT,
                  last_true_pose=last_true, last_odom_pose=last_odom)
    return result


def run_route(keys, start_pose, follower, max_steps, *, odom_error=None, world=None):
    """Drive a whole route (lane_coverage's tour) offline: run_scenario's
    loop (same renderer, CORE law, 3 s lease, odometry error) from
    `start_pose` until the TRUE pose's route coordinate (junction_score's
    windowed projection, anchored on the first key) reaches the start point
    again on the last key, CORE's lease latches LOST, or `max_steps`. The
    world defaults to TOUR_WORLD.
    Scored with junction_score.score_route; the result adds the track,
    tiers, reason, stall times, last true / odometry poses and `steps`."""
    world = TOUR_WORLD if world is None else world
    error = OdomError() if odom_error is None else odom_error
    pose = tuple(float(v) for v in start_pose)
    odom = believed_start({"start": pose}, error)
    path, arc, starts = junction_score.route_path(GRAPH, keys)
    last_key = junction_score.directed_points(GRAPH, keys[-1])
    s_end = float(starts[-2] + junction_score._nearest_on_path(
        last_key, junction_score._arc_length(last_key), pose[:2])[0])
    s, _ = junction_score._nearest_on_path(path, arc, pose[:2], (0.0, float(starts[1])))
    track, tiers = [pose[:2]], []
    reason, loss_started, stall, stretch, max_stretch = None, None, 0, 0, 0
    last_true, last_odom = pose, odom
    step = 0
    for step in range(max_steps):
        now = step * lane_sim.DT
        last_true, last_odom = pose, odom
        observation = follower.update(now, odom, world.render(pose),
                                      lane_sim.GROUND, **lane_sim.KW)
        tiers.append(getattr(follower, "state", "-"))
        if observation is None or observation.confidence < CORE_MIN_CONFIDENCE:
            stall += 1
            stretch += 1
            max_stretch = max(max_stretch, stretch)
            loss_started = now if loss_started is None else loss_started
            if now - loss_started > LOST_AFTER_S:
                reason = "lost"
                break
        else:
            loss_started, stretch = None, 0
        linear, angular = lane_sim.core_command(observation)
        pose = _integrate(pose, linear, angular)
        moving = linear > 0.0 or angular != 0.0
        odom = _integrate(odom, (1.0 + error.scale) * linear,
                          (1.0 + error.scale) * angular
                          + (error.yaw_rate_bias if moving else 0.0))
        track.append(pose[:2])
        s, _ = junction_score._nearest_on_path(
            path, arc, pose[:2], (s - junction_score.SEARCH_WINDOW_M,
                                  s + junction_score.SEARCH_WINDOW_M))
        if s >= s_end:
            break
    result = junction_score.score_route(GRAPH, keys, track, lost=reason is not None)
    result.update(track=track, tiers=tiers, final_pose=pose, reason=reason,
                  stall_s=stall * lane_sim.DT, max_stall_s=max_stretch * lane_sim.DT,
                  last_true_pose=last_true, last_odom_pose=last_odom, steps=step + 1)
    return result


def summary(results):
    """One line per scenario for a test failure message."""
    return "\n".join(
        f"{r['scenario']['node']:>2} {r['scenario']['into']:>9} -> {r['scenario']['out']:<9}"
        f" pass={r['pass']} dev={r['max_centre_dev_m']:.3f}"
        f" wrong_way={r['wrong_way']} ccw={r['ring_ccw_ok']}"
        for r in results)
