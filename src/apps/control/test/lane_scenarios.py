"""Offline closed loop for the 12 junction scenarios (test helper).

Same three parts as the Gazebo harness, minus Gazebo: lane_sim renders the
STL paint through the declared camera, CORE's law turns an observation into
a command, and junction_score judges the resulting track (direction-aware).
A follower here is anything with `.update(now_s, pose, bgr, ground, **KW)`
returning a LaneObservation or None, like LaneBoundaryTracker.
"""

import importlib.util
import math
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


def run_scenario(scenario, follower, *, steps=200, world=None):
    """Drive one scenario offline; return the track, the score and the tiers."""
    world = WORLD if world is None else world
    pose = tuple(scenario["start"])
    track, tiers = [pose[:2]], []
    end = junction_score.directed_points(GRAPH, scenario["out"])
    end_s = junction_score._arc_length(end)
    end_point = end[int(end_s.searchsorted(junction_score.END_AFTER_M))]
    for step in range(steps):
        observation = follower.update(step * lane_sim.DT, pose, world.render(pose),
                                      lane_sim.GROUND, **lane_sim.KW)
        tiers.append(getattr(follower, "state", "-"))
        linear, angular = lane_sim.core_command(observation)
        mid = pose[2] + angular * lane_sim.DT / 2.0
        pose = (pose[0] + linear * lane_sim.DT * math.cos(mid),
                pose[1] + linear * lane_sim.DT * math.sin(mid),
                pose[2] + angular * lane_sim.DT)
        track.append(pose[:2])
        if math.dist(pose[:2], end_point) < 0.05:
            break
    result = junction_score.score(GRAPH, scenario, track)
    result.update(track=track, tiers=tiers, final_pose=pose)
    return result


def summary(results):
    """One line per scenario for a test failure message."""
    return "\n".join(
        f"{r['scenario']['node']:>2} {r['scenario']['into']:>9} -> {r['scenario']['out']:<9}"
        f" pass={r['pass']} dev={r['max_centre_dev_m']:.3f}"
        f" wrong_way={r['wrong_way']} ccw={r['ring_ccw_ok']}"
        for r in results)
