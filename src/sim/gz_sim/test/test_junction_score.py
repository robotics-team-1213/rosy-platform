"""Junction scenarios from the lane graph, and trajectory scoring (spec §4.4)."""

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT.parents[1] / "apps" / "control" / "map" / "map_v2_fleet" / "lane_graph.yaml"


def _mod():
    spec = importlib.util.spec_from_file_location("junction_score", ROOT / "scripts" / "junction_score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def graph():
    return yaml.safe_load(GRAPH.read_text(encoding="utf-8"))


def test_twelve_transitions_three_per_node(graph):
    scenarios = _mod().scenarios(graph)
    assert len(scenarios) == 12
    per_node = {}
    for s in scenarios:
        per_node[s["node"]] = per_node.get(s["node"], 0) + 1
    assert per_node == {"NE": 3, "NW": 3, "SE": 3, "SW": 3}


def test_ring_is_only_entered_counter_clockwise(graph):
    for s in _mod().scenarios(graph):
        assert s["into"] not in ("ring_n:r", "ring_w:r", "ring_s:r", "ring_e:r")
        assert s["out"] not in ("ring_n:r", "ring_w:r", "ring_s:r", "ring_e:r")


def test_start_pose_is_on_the_incoming_centreline_heading_along_it(graph):
    """START_BEFORE_M is an arc-length offset along `into`'s centreline, not
    a straight-line distance to the node: the ring's radius (0.2514 m) is
    tight enough that a 0.35 m arc back from a node is only ~0.32 m from it
    as the crow flies (chord < arc on a curve). Check arc length instead."""
    mod = _mod()
    for s in mod.scenarios(graph):
        x, y, yaw = s["start"]
        pts = mod.directed_points(graph, s["into"])
        d = mod.distance_to(pts, (x, y))
        assert d < 0.005
        arc = mod._arc_length(pts)
        i = int(np.argmin(np.abs(pts[:, 0] - x) + np.abs(pts[:, 1] - y)))
        assert arc[-1] - arc[i] == pytest.approx(mod.START_BEFORE_M, abs=0.01)


def test_centreline_trajectory_scores_as_a_pass(graph):
    mod = _mod()
    s = mod.scenarios(graph)[0]
    path = np.vstack([mod.directed_points(graph, s["into"])[-40:],
                      mod.directed_points(graph, s["out"])[:40]])
    result = mod.score(graph, s, path)
    assert result["branch_ok"] and result["reached_end"]
    assert result["max_centre_dev_m"] < 0.005


def test_wrong_branch_is_detected(graph):
    """NW's three scenarios; the first two have different `out`s (ring_w:f
    and west:r), so a trajectory that follows the first's `into` but the
    second's `out` takes an exit the first scenario never allows."""
    mod = _mod()
    by_node = [s for s in mod.scenarios(graph) if s["node"] == "NW"]
    good, other = by_node[0], by_node[1]
    assert good["out"] != other["out"]
    path = np.vstack([mod.directed_points(graph, good["into"])[-40:],
                      mod.directed_points(graph, other["out"])[:40]])
    assert not mod.score(graph, good, path)["branch_ok"]


def test_a_different_allowed_exit_from_the_same_node_also_fails_branch_ok(graph):
    """Two NW scenarios share `into` (ring_n:f) but leave on different exits
    (ring_w:f and west:r): taking the wrong one of those two allowed exits
    must still fail branch_ok for the scenario that wanted the other."""
    mod = _mod()
    by_node = [s for s in mod.scenarios(graph) if s["node"] == "NW"]
    shared_into = [s for s in by_node if s["into"] == "ring_n:f"]
    assert len(shared_into) == 2
    wanted, taken = shared_into[0], shared_into[1]
    assert wanted["out"] != taken["out"]
    path = np.vstack([mod.directed_points(graph, wanted["into"])[-40:],
                      mod.directed_points(graph, taken["out"])[:40]])
    assert not mod.score(graph, wanted, path)["branch_ok"]


def test_off_centre_trajectory_reports_its_deviation(graph):
    mod = _mod()
    s = mod.scenarios(graph)[0]
    pts = np.vstack([mod.directed_points(graph, s["into"])[-40:],
                     mod.directed_points(graph, s["out"])[:40]])
    shifted = pts + np.array([0.03, 0.0])
    assert mod.score(graph, s, shifted)["max_centre_dev_m"] == pytest.approx(0.03, abs=0.01)
