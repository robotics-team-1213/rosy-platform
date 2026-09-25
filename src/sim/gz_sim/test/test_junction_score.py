"""Junction scenarios from the lane graph, and trajectory scoring (spec §4.4)."""

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT.parents[1] / "runtime" / "sensing" / "map" / "map_v2_fleet" / "lane_graph.yaml"


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


#: 01/05/06/10: NE ring_e:f->east:f, NW west:f->ring_w:f, SE east:f->ring_e:f,
#: SW ring_w:f->west:f. Each pair (east/ring_e, west/ring_w) joins the SAME
#: two nodes by a different route, so distance-to-line membership alone
#: cannot tell a real transit from a pivot U-turn back along `into`, round
#: the far node, and backwards along `out` -- the review's exact finding.
UTURN_PRONE_INDICES = (1, 5, 6, 10)


def _forward_path(graph, mod, s):
    return np.vstack([mod.directed_points(graph, s["into"])[-40:],
                      mod.directed_points(graph, s["out"])[:40]])


def test_uturn_prone_scenarios_are_the_reviewed_same_node_pairs(graph):
    mod = _mod()
    scenarios = mod.scenarios(graph)
    pairs = {tuple(sorted((scenarios[i]["into"].split(":")[0], scenarios[i]["out"].split(":")[0])))
             for i in UTURN_PRONE_INDICES}
    assert pairs == {("east", "ring_e"), ("ring_w", "west")}


def test_a_pivot_uturn_back_along_into_and_out_fails_branch_ok():
    """The forward path used elsewhere in this file, played backwards in
    time: same points (so distance-to-line and "reached end" cannot tell
    the difference), opposite direction of travel."""
    mod = _mod()
    graph = yaml.safe_load(GRAPH.read_text(encoding="utf-8"))
    scenarios = mod.scenarios(graph)
    for i in UTURN_PRONE_INDICES:
        s = scenarios[i]
        forward = _forward_path(graph, mod, s)
        uturn = np.flip(forward, axis=0)
        result = mod.score(graph, s, uturn)
        assert result["wrong_way"], s
        assert not result["branch_ok"], s
        assert not result["pass"], s


def test_a_clean_forward_trajectory_through_the_uturn_prone_pairs_still_passes():
    """The fix must not cost the legitimate transitions their pass."""
    mod = _mod()
    graph = yaml.safe_load(GRAPH.read_text(encoding="utf-8"))
    scenarios = mod.scenarios(graph)
    for i in UTURN_PRONE_INDICES:
        s = scenarios[i]
        result = mod.score(graph, s, _forward_path(graph, mod, s))
        assert not result["wrong_way"], s
        assert result["branch_ok"], s
        assert result["pass"], s


def test_small_jitter_does_not_trigger_wrong_way(graph):
    """A smooth +-1 cm wobble along the path (not point-to-point noise,
    which would locally reverse direction by construction) must not be
    mistaken for a U-turn."""
    mod = _mod()
    s = mod.scenarios(graph)[0]
    pts = _forward_path(graph, mod, s)
    n = len(pts)
    wobble = 0.01 * np.stack(
        [np.sin(np.linspace(0, 2 * math.pi, n)), np.cos(np.linspace(0, 2 * math.pi, n))], axis=1)
    result = mod.score(graph, s, pts + wobble)
    assert not result["wrong_way"]
    assert result["branch_ok"]


def test_ring_ccw_ok_is_true_for_the_graphs_own_ring_arcs(graph):
    mod = _mod()
    for name in ("ring_n:f", "ring_w:f", "ring_s:f", "ring_e:f"):
        assert mod._ring_ccw_ok(graph, mod.directed_points(graph, name))


def test_ring_ccw_ok_is_false_for_a_clockwise_ring_trajectory(graph):
    mod = _mod()
    centre = np.array(graph["roundabout"]["centre"], float)
    angles = np.linspace(0.0, -math.pi, 50)  # decreasing angle = clockwise
    clockwise = centre + 0.25 * np.stack([np.cos(angles), np.sin(angles)], axis=1)
    assert not mod._ring_ccw_ok(graph, clockwise)
    s = mod.scenarios(graph)[0]
    result = mod.score(graph, s, clockwise)
    assert not result["ring_ccw_ok"]
    assert not result["pass"]


def test_rescore_reproduces_score_from_recorded_track_json_files(graph, tmp_path):
    """rescore() is how the coordinator re-scores existing WSL evidence
    (results.json + per-scenario track.json folders) against a fixed
    junction_score.py without re-running Gazebo."""
    mod = _mod()
    scenarios = mod.scenarios(graph)[:2]
    stale_results = []
    expected = []
    for idx, s in enumerate(scenarios):
        path = _forward_path(graph, mod, s)
        folder = tmp_path / f"{idx:02d}_{s['node']}_{s['into']}_to_{s['out']}".replace(":", "")
        folder.mkdir()
        (folder / "track.json").write_text(json.dumps(path.tolist()))
        stale_results.append(dict(s, pass_=False, reason="reached"))  # a plausibly-stale old score
        expected.append(mod.score(graph, s, path))
    (tmp_path / "results.json").write_text(json.dumps(stale_results))

    rescored = mod.rescore(graph, tmp_path / "results.json", tmp_path)
    assert len(rescored) == 2
    for entry, want in zip(rescored, expected):
        assert entry["pass"] == want["pass"]
        assert entry["branch_ok"] == want["branch_ok"]
        assert entry["wrong_way"] == want["wrong_way"]
        # the harness's own scenario/reason fields survive the merge
        assert entry["reason"] == "reached"


def test_rescore_falls_back_to_the_start_pose_when_a_track_file_is_missing(graph, tmp_path):
    mod = _mod()
    s = mod.scenarios(graph)[0]
    (tmp_path / "results.json").write_text(json.dumps([dict(s, pass_=None)]))
    rescored = mod.rescore(graph, tmp_path / "results.json", tmp_path)
    assert len(rescored) == 1
    assert rescored[0]["reached_end"] is False  # a single point can't reach the end


def test_rescore_cli_writes_a_rescored_json_next_to_results(graph, tmp_path):
    mod = _mod()
    s = mod.scenarios(graph)[0]
    folder = tmp_path / f"00_{s['node']}_{s['into']}_to_{s['out']}".replace(":", "")
    folder.mkdir()
    path = _forward_path(graph, mod, s)
    (folder / "track.json").write_text(json.dumps(path.tolist()))
    (tmp_path / "results.json").write_text(json.dumps([dict(s, pass_=None)]))
    graph_path = GRAPH
    rc = mod._rescore_cli(["--graph", str(graph_path), "--results", str(tmp_path / "results.json"),
                           "--tracks", str(tmp_path)])
    assert rc == 0
    out_path = tmp_path / "results_rescored.json"
    assert out_path.is_file()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written[0]["pass"] is True


#: lane_coverage's map_v2_fleet tour (test_lane_coverage pins it).
TOUR = ["west:f", "ring_w:f", "ring_s:f", "east:r", "ring_n:f", "west:r", "ring_s:f",
        "ring_e:f", "east:f", "ring_e:f", "ring_n:f", "ring_w:f", "west:f"]


def _tour_track(graph, lateral=0.0, step=0.01):
    """The tour's centreline from the parking junction back to it, `lateral`
    to the left, sampled every `step` metres."""
    mod = _mod()
    start = np.asarray(graph["parking"]["points"][0], float)
    path, arc, starts = mod.route_path(graph, TOUR)
    first = mod.directed_points(graph, TOUR[0])
    s0, _ = mod._nearest_on_path(first, mod._arc_length(first), start)
    s_end = starts[-2] + s0
    track = []
    for s in np.arange(s0, s_end + 1e-9, step):
        i = min(int(np.searchsorted(arc, s, side="right")) - 1, len(path) - 2)
        d = path[i + 1] - path[i]
        d = d / np.linalg.norm(d)
        track.append(path[i] + d * (s - arc[i]) + lateral * np.array([-d[1], d[0]]))
    track.append(start)
    return [tuple(p) for p in track]


def test_the_tour_driven_on_its_centreline_passes(graph):
    result = _mod().score_route(graph, TOUR, _tour_track(graph))
    assert result["pass"], result
    assert result["missing"] == []
    assert all(result["segments_driven"])
    assert result["end_distance_m"] <= 0.01
    assert result["route_length_m"] == pytest.approx(16.874, abs=0.02)


def test_a_tour_stopped_halfway_misses_segments(graph):
    track = _tour_track(graph)
    result = _mod().score_route(graph, TOUR, track[:len(track) // 2])
    assert not result["pass"]
    assert "east:f" in result["missing"]
    assert result["end_distance_m"] > 0.05


def test_a_tour_driven_backwards_is_wrong_way(graph):
    result = _mod().score_route(graph, TOUR, _tour_track(graph)[::-1])
    assert not result["pass"]
    assert result["wrong_way"] or not result["ring_ccw_ok"]


def test_a_tour_off_the_centreline_fails_on_deviation(graph):
    result = _mod().score_route(graph, TOUR, _tour_track(graph, lateral=0.05))
    assert not result["pass"]
    assert result["max_centre_dev_m"] > 0.04


def test_a_lost_tour_fails(graph):
    result = _mod().score_route(graph, TOUR, _tour_track(graph), lost=True)
    assert not result["pass"] and result["lost"]


def test_a_tour_cut_short_misses_the_rest(graph):
    """A track that ends where east:f ends (the tour's second ring_e:f
    cannot be skipped by a connected route: east:f -> ring_n:f does not
    exist) scores the first nine keys driven and the rest not."""
    mod = _mod()
    track = _tour_track(graph)
    path, arc, starts = mod.route_path(graph, TOUR)
    first = mod.directed_points(graph, TOUR[0])
    s0, _ = mod._nearest_on_path(first, mod._arc_length(first), track[0])
    cut = int((starts[9] - s0) / 0.01)
    result = mod.score_route(graph, TOUR, track[:cut])
    assert not result["pass"]
    assert result["segments_driven"][:9] == [True] * 9
    assert not any(result["segments_driven"][9:])
    assert "ring_e:f" not in result["missing"]      # driven once already
