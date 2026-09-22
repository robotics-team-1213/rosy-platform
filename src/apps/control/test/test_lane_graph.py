"""260919 lane graph: rules anchors snapped to the STL paint (spec §4.1)."""

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

BUNDLE = Path(__file__).resolve().parents[1] / "map" / "map_v2_fleet"


def _module():
    spec = importlib.util.spec_from_file_location("lane_graph", BUNDLE / "scripts" / "lane_graph.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def graph():
    return yaml.safe_load((BUNDLE / "lane_graph.yaml").read_text(encoding="utf-8"))


def test_four_ring_nodes_and_six_segments(graph):
    assert sorted(graph["nodes"]) == ["NE", "NW", "SE", "SW"]
    assert sorted(graph["segments"]) == ["east", "ring_e", "ring_n", "ring_s", "ring_w", "west"]


def test_ring_is_one_way_ccw_and_roads_are_two_way(graph):
    seg = graph["segments"]
    for name in ("ring_n", "ring_w", "ring_s", "ring_e"):
        assert seg[name]["directions"] == ["forward"]
    for name in ("west", "east"):
        assert seg[name]["directions"] == ["forward", "reverse"]
    # CCW: each arc's heading turns left (positive cross product).
    for name in ("ring_n", "ring_w", "ring_s", "ring_e"):
        p = np.array(seg[name]["points"])
        a, b = p[1] - p[0], p[2] - p[1]
        assert a[0] * b[1] - a[1] * b[0] > 0


def test_segments_join_at_their_nodes(graph):
    nodes = {k: np.array(v) for k, v in graph["nodes"].items()}
    for name, seg in graph["segments"].items():
        p = np.array(seg["points"])
        assert np.linalg.norm(p[0] - nodes[seg["from"]]) < 1e-3, name
        assert np.linalg.norm(p[-1] - nodes[seg["to"]]) < 1e-3, name


def test_centrelines_keep_clear_of_the_boundary_lines(graph):
    """Every centre point 60-100 mm from the nearest boundary line, except
    within NODE_EXEMPT_M of a junction node where the lane mouth widens."""
    mod = _module()
    field = mod.LineField(mod.load_scene())
    assert mod.clearance_violations(graph, field) == []


def test_lengths_are_plausible(graph):
    seg = graph["segments"]
    ring = sum(seg[n]["length_m"] for n in ("ring_n", "ring_w", "ring_s", "ring_e"))
    assert ring == pytest.approx(2 * math.pi * graph["roundabout"]["radius"], rel=0.01)
    assert 2.6 < seg["west"]["length_m"] < 3.1
    assert 3.2 < seg["east"]["length_m"] < 4.2


def test_parking_spur_runs_from_the_left_lane_into_the_west_block(graph):
    park = graph["parking"]
    p = np.array(park["points"])
    assert park["road"] == "west"
    assert p[0] == pytest.approx([-1.2696, 0.0], abs=0.01)
    assert p[-1] == pytest.approx([-1.0, 0.0], abs=0.01)


def test_generator_output_is_checked_in_and_deterministic(tmp_path):
    mod = _module()
    out = tmp_path / "lane_graph.yaml"
    mod.write(mod.build(), out)
    assert out.read_bytes() == (BUNDLE / "lane_graph.yaml").read_bytes()
