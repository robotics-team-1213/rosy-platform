"""ROS-free tests for live_view_model.py, the pure logic behind the live
viewer (lane_live_view.py): confidence tier, phase derivation, route
progress, clock health, the spot error and the evidence-run listing."""

import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT.parents[1] / "apps" / "control" / "map" / "map_v2_fleet" / "lane_graph.yaml"


def _mod():
    spec = importlib.util.spec_from_file_location(
        "live_view_model", ROOT / "scripts" / "live_view_model.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_view_model"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _mod()


@pytest.fixture(scope="module")
def graph():
    return yaml.safe_load(GRAPH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------
# Confidence tier (inferred: the tier is not on the wire)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("obs, tier", [
    ({"visible": True, "confidence": 0.95}, "BOTH"),
    ({"visible": True, "confidence": 0.85}, "BOTH"),
    ({"visible": True, "confidence": 0.8}, "ONE"),
    ({"visible": True, "confidence": 0.7}, "ONE"),
    ({"visible": True, "confidence": 0.6}, "MEMORY"),
    ({"visible": True, "confidence": 0.4}, "MEMORY"),
    ({"visible": True, "confidence": 0.2}, "STOP"),
    ({"visible": False, "confidence": 0.9}, "STOP"),
    ({"visible": True, "confidence": None}, "STOP"),
    ({}, None),
    (None, None),
])
def test_classify_tier(m, obs, tier):
    assert m.classify_tier(obs) == tier


def test_tier_stats_distribution_is_percent_of_samples(m):
    stats = m.TierStats()
    for tier in ["BOTH"] * 6 + ["ONE"] * 2 + ["MEMORY"] + ["STOP"]:
        stats.add(tier)
    dist = stats.snapshot()
    assert dist["samples"] == 10
    assert dist["pct"] == {"BOTH": 60.0, "ONE": 20.0, "MEMORY": 10.0, "STOP": 10.0}


def test_tier_stats_empty_and_reset(m):
    stats = m.TierStats()
    assert stats.snapshot() == {"samples": 0, "pct": {"BOTH": 0.0, "ONE": 0.0,
                                                      "MEMORY": 0.0, "STOP": 0.0}}
    stats.add("BOTH")
    stats.add(None)  # no observation: not a sample
    assert stats.snapshot()["samples"] == 1
    stats.reset()
    assert stats.snapshot()["samples"] == 0


def test_history_keeps_only_the_window(m):
    hist = m.History(window_s=60.0)
    hist.add(0.0, 0.01, 0.9, "BOTH")
    hist.add(30.0, 0.02, 0.8, "ONE")
    hist.add(61.0, -0.03, 0.6, "MEMORY")
    series = hist.series(now=61.0)
    assert [p[0] for p in series] == [-31.0, 0.0]  # seconds relative to now
    assert series[-1] == [0.0, -0.03, 0.6, "MEMORY"]


# ---------------------------------------------------------------------
# Spot error
# ---------------------------------------------------------------------


def test_spot_error_within_target(m):
    err = m.spot_error((-0.99, 0.005, math.radians(2.0)), (-1.0, 0.0, 0.0))
    assert err["dist_m"] == pytest.approx(math.hypot(0.01, 0.005), abs=1e-4)
    assert err["heading_err_deg"] == pytest.approx(2.0, abs=1e-3)
    assert err["ok"] is True


def test_spot_error_heading_wraps_and_fails_outside_target(m):
    err = m.spot_error((-1.0, 0.0, math.radians(354.0)), (-1.0, 0.0, 0.0))
    assert err["heading_err_deg"] == pytest.approx(-6.0, abs=1e-3)
    assert err["ok_position"] is True
    assert err["ok_heading"] is False
    assert err["ok"] is False
    far = m.spot_error((-0.97, 0.0, 0.0), (-1.0, 0.0, 0.0))
    assert far["ok_position"] is False


# ---------------------------------------------------------------------
# Mission phase
# ---------------------------------------------------------------------


def _phase(m, prev=None, core_ok=True, docking=None, line_mode="OFF",
           log_phase=None, route_done=False):
    return m.derive_phase(prev, core_ok=core_ok, docking=docking, line_mode=line_mode,
                          log_phase=log_phase, route_done=route_done)


def test_phase_is_boot_until_core_answers(m):
    assert _phase(m, core_ok=False) == "boot"
    assert _phase(m, core_ok=True, docking="UNDOCKED") == "boot"


def test_core_blip_keeps_the_current_phase(m):
    assert _phase(m, prev="tour", core_ok=False) == "tour"


def test_phase_follows_the_mission_sequence(m):
    assert _phase(m, prev="boot", docking="DOCKING") == "confirm"
    assert _phase(m, prev="confirm", docking="DOCKED") == "confirm"
    assert _phase(m, prev="confirm", docking="UNDOCKING") == "undock"
    assert _phase(m, prev="undock", docking="UNDOCKED") == "undock"
    assert _phase(m, prev="undock", docking="UNDOCKED", line_mode="CAMERA_LINE") == "tour"
    assert _phase(m, prev="tour", docking="UNDOCKED") == "tour"
    assert _phase(m, prev="tour", docking="DOCKING") == "park"
    assert _phase(m, prev="park", docking="DOCKED") == "done"
    assert _phase(m, prev="done", docking="DOCKED") == "done"


def test_docked_after_a_finished_route_is_done(m):
    assert _phase(m, prev=None, docking="DOCKED", route_done=True) == "done"
    assert _phase(m, prev=None, docking="DOCKING", route_done=True) == "park"


def test_a_fresh_mission_log_wins(m):
    assert _phase(m, prev="boot", docking="UNDOCKED", log_phase="tour") == "tour"
    assert _phase(m, prev="tour", docking="DOCKED", log_phase="park") == "done"
    assert _phase(m, prev=None, core_ok=False, log_phase="confirm") == "confirm"


def test_phase_labels_are_korean_and_ordered(m):
    assert m.PHASES == ("boot", "confirm", "undock", "tour", "park", "done")
    assert [m.PHASE_LABELS[p] for p in m.PHASES] == [
        "부팅", "칸 확인", "출차", "순회", "주차", "완료"]


# ---------------------------------------------------------------------
# Clock health
# ---------------------------------------------------------------------


def test_clock_rtf_over_the_window(m):
    clock = m.ClockMonitor(window_s=5.0, offset=100.0)
    for i in range(11):
        clock.on_clock(sim_s=10.0 + 0.25 * i, wall_mono=50.0 + 0.5 * i)
    snap = clock.snapshot(wall_mono=55.0, offset=100.0)
    assert snap["sim_s"] == pytest.approx(12.5)
    assert snap["rtf"] == pytest.approx(0.5, abs=1e-3)
    assert snap["age_s"] == pytest.approx(0.0)
    assert snap["step_s"] == 0.0
    assert snap["step_warn"] is False


def test_clock_step_warns_when_the_wall_clock_jumps(m):
    clock = m.ClockMonitor(window_s=5.0, offset=100.0)
    clock.on_clock(sim_s=1.0, wall_mono=1.0)
    snap = clock.snapshot(wall_mono=1.0, offset=101.6)
    assert snap["step_s"] == pytest.approx(1.6)
    assert snap["step_warn"] is True


def test_clock_before_any_message_reports_nothing(m):
    snap = m.ClockMonitor().snapshot(wall_mono=3.0, offset=0.0)
    assert snap["sim_s"] is None
    assert snap["rtf"] is None
    assert snap["age_s"] is None


def test_clock_going_backwards_restarts_the_window(m):
    clock = m.ClockMonitor(window_s=5.0, offset=0.0)
    clock.on_clock(sim_s=300.0, wall_mono=1.0)
    clock.on_clock(sim_s=301.0, wall_mono=2.0)
    assert clock.on_clock(sim_s=0.1, wall_mono=3.0) is True  # a relaunch
    clock.on_clock(sim_s=0.6, wall_mono=4.0)
    assert clock.snapshot(wall_mono=4.0, offset=0.0)["rtf"] == pytest.approx(0.5)


# ---------------------------------------------------------------------
# Route progress
# ---------------------------------------------------------------------


def _route_points(graph, keys, step=0.02):
    """Densely sampled polyline of the whole route, first key to last."""
    pts = []
    for key in keys:
        name, way = key.split(":")
        seg = [tuple(p) for p in graph["segments"][name]["points"]]
        pts.extend(seg if way == "f" else seg[::-1])
    return pts


def test_tour_route_is_the_13_key_all_lane_tour(m, graph):
    keys = m.tour_keys(graph)
    assert len(keys) == 13
    assert len(set(keys)) == 8


def test_route_progress_starts_at_zero(m, graph):
    route = m.RouteProgress(graph, m.tour_keys(graph))
    snap = route.snapshot()
    assert snap["length_m"] == pytest.approx(16.874, abs=0.01)
    assert snap["progress_m"] == 0.0
    assert snap["segment_index"] == 0
    assert snap["done_unique"] == 0
    assert snap["total_unique"] == 8
    assert snap["key_states"][0] == "current"
    assert set(snap["key_states"][1:]) == {"todo"}
    assert snap["finished"] is False


def test_route_progress_follows_a_full_drive(m, graph):
    keys = m.tour_keys(graph)
    route = m.RouteProgress(graph, keys)
    start = tuple(graph["parking"]["points"][0])
    pts = _route_points(graph, keys)
    # Drive from the start point on the first key to the start point on the
    # last one: skip the first key's part behind the start.
    i0 = min(range(len(pts) // 4), key=lambda i: math.dist(pts[i], start))
    i1 = max(range(len(pts) * 3 // 4, len(pts)), key=lambda i: -math.dist(pts[i], start))
    for p in pts[i0:i1 + 1]:
        route.update(p)
    snap = route.snapshot()
    assert snap["progress_m"] == pytest.approx(snap["length_m"], abs=0.05)
    assert snap["finished"] is True
    assert snap["done_unique"] == 8
    assert set(snap["key_states"]) == {"done"}


def test_route_progress_midway_marks_done_current_todo(m, graph):
    keys = m.tour_keys(graph)
    route = m.RouteProgress(graph, keys)
    start = tuple(graph["parking"]["points"][0])
    pts = _route_points(graph, keys)
    i0 = min(range(len(pts) // 4), key=lambda i: math.dist(pts[i], start))
    for p in pts[i0:i0 + len(pts) // 2]:
        route.update(p)
    snap = route.snapshot()
    idx = snap["segment_index"]
    assert 3 <= idx <= 9
    assert snap["key_states"][:idx] == ["done"] * idx
    assert snap["key_states"][idx] == "current"
    assert snap["key_states"][idx + 1:] == ["todo"] * (len(keys) - idx - 1)
    assert snap["current_key"] == keys[idx]
    assert 1 <= snap["done_unique"] < 8
    assert 5.0 < snap["progress_m"] < 12.0


def test_route_progress_is_forward_only(m, graph):
    keys = m.tour_keys(graph)
    route = m.RouteProgress(graph, keys)
    start = tuple(graph["parking"]["points"][0])
    pts = _route_points(graph, keys)
    i0 = min(range(len(pts) // 4), key=lambda i: math.dist(pts[i], start))
    for p in pts[i0:i0 + 60]:
        route.update(p)
    ahead = route.snapshot()["progress_m"]
    route.update(pts[i0 + 30])  # a noisy fix behind the robot
    assert route.snapshot()["progress_m"] == ahead


def test_route_progress_ignores_poses_off_the_route(m, graph):
    route = m.RouteProgress(graph, m.tour_keys(graph))
    assert route.update((-1.0, 0.0)) is False  # the parking spot, off the lane
    assert route.snapshot()["progress_m"] == 0.0


def test_route_progress_reset(m, graph):
    keys = m.tour_keys(graph)
    route = m.RouteProgress(graph, keys)
    start = tuple(graph["parking"]["points"][0])
    pts = _route_points(graph, keys)
    i0 = min(range(len(pts) // 4), key=lambda i: math.dist(pts[i], start))
    for p in pts[i0:i0 + 60]:
        route.update(p)
    route.reset()
    assert route.snapshot()["progress_m"] == 0.0


# ---------------------------------------------------------------------
# Evidence runs
# ---------------------------------------------------------------------


def _write(path, obj, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    os.utime(path, (mtime, mtime))
    os.utime(path.parent, (mtime, mtime))


@pytest.fixture()
def evidence(tmp_path):
    base = 1_790_000_000
    scen = {"node": "NE", "into": "east:r", "out": "ring_n:f", "pass": True,
            "reason": "reached", "max_centre_dev_m": 0.0346, "sim_s": 16.18}
    _write(tmp_path / "junctions_route_ab_r1" / "results.json",
           [scen, dict(scen, node="SW", max_centre_dev_m=0.051, sim_s=20.0,
                       **{"pass": False})], base + 10)
    _write(tmp_path / "junctions_route_ab_r1" / "00_NE_x" / "track.json",
           [[0.0, 0.0], [0.1, 0.0]], base + 10)
    _write(tmp_path / "tour_t4" / "results.json",
           {"pass": True, "reason": "reached", "max_centre_dev_m": 0.0352,
            "end_distance_m": 0.0027, "sim_s": 351.49, "real_time_factor": 0.312,
            "progress_m": 16.871, "route_length_m": 16.874}, base + 20)
    _write(tmp_path / "tour_t4" / "track.json", [[-1.27, 0.0], [-1.27, 0.1]], base + 20)
    _write(tmp_path / "mission_m6" / "results.json",
           {"pass": True, "reason": "parked", "park_error_m": 0.0023, "park_dyaw_deg": 1.71,
            "sim_s": 378.22, "real_time_factor": 0.464,
            "tour": {"max_centre_dev_m": 0.0371, "pass": True}}, base + 30)
    _write(tmp_path / "mission_m6" / "track.json",
           [[-1.0, 0.0, 0.0, 0.1, "confirm"], [-1.1, 0.0, 0.0, 1.5, "undock"],
            [-1.27, 0.1, 1.5, 9.5, "tour"], [-1.27, 0.2, 1.5, 9.6, "tour"]], base + 30)
    _write(tmp_path / "tour_" / "core_status.jsonl", "", base + 5)
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    return tmp_path


def test_list_runs_newest_first_with_type_tag_and_verdict(m, evidence):
    runs = m.list_runs(evidence)
    assert [r["id"] for r in runs] == ["mission_m6", "tour_t4", "junctions_route_ab_r1", "tour_"]
    mission, tour, junctions, empty = runs
    assert (mission["kind"], mission["label"], mission["tag"]) == ("mission", "미션", "m6")
    assert mission["pass"] is True
    assert mission["metrics"]["max_dev_m"] == 0.0371
    assert mission["metrics"]["park_error_m"] == 0.0023
    assert mission["metrics"]["park_dyaw_deg"] == 1.71
    assert mission["metrics"]["sim_s"] == 378.22
    assert (tour["kind"], tour["label"], tour["tag"]) == ("tour", "순회", "t4")
    assert tour["metrics"]["end_error_m"] == 0.0027
    assert tour["metrics"]["max_dev_m"] == 0.0352
    assert (junctions["kind"], junctions["label"]) == ("junctions", "교차로")
    assert junctions["pass"] is False
    assert junctions["metrics"]["scenarios"] == 2
    assert junctions["metrics"]["passed"] == 1
    assert junctions["metrics"]["max_dev_m"] == 0.051
    assert junctions["metrics"]["sim_s"] == pytest.approx(36.18)
    assert empty["pass"] is None  # no results.json yet
    assert empty["tag"] == ""


def test_list_runs_on_a_missing_dir_is_empty(m, tmp_path):
    assert m.list_runs(tmp_path / "nope") == []


def test_load_run_returns_summary_and_tracks(m, evidence):
    run = m.load_run(evidence, "mission_m6")
    assert run["summary"]["id"] == "mission_m6"
    labels = [t["label"] for t in run["tracks"]]
    assert labels == ["confirm", "undock", "tour"]
    assert run["tracks"][2]["points"] == [[-1.27, 0.1], [-1.27, 0.2]]
    assert run["results"]["reason"] == "parked"


def test_load_run_of_junctions_has_one_track_per_scenario(m, evidence):
    run = m.load_run(evidence, "junctions_route_ab_r1")
    assert [t["label"] for t in run["tracks"]] == ["00_NE_x"]


def test_load_run_rejects_unknown_and_traversal_ids(m, evidence):
    assert m.load_run(evidence, "../etc") is None
    assert m.load_run(evidence, "mission_nope") is None
    assert m.load_run(evidence, "notes.txt") is None


def test_track_downsampling_keeps_ends(m):
    pts = [[float(i), 0.0] for i in range(5000)]
    out = m.downsample(pts, 500)
    assert len(out) <= 501
    assert out[0] == pts[0] and out[-1] == pts[-1]


def test_live_log_phase_reads_the_newest_fresh_mission(m, evidence):
    log = evidence / "mission_m7" / "core_status.jsonl"
    lines = [{"sim": 1.0, "phase": "confirm"}, {"sim": 12.5, "phase": "tour"}]
    _write(log, "\n".join(json.dumps(x) for x in lines) + "\n", 1_790_000_100)
    live = m.live_log_phase(evidence, now_wall=1_790_000_102, fresh_s=5.0)
    assert live == {"run": "mission_m7", "phase": "tour", "sim": 12.5}
    assert m.live_log_phase(evidence, now_wall=1_790_000_200, fresh_s=5.0) is None


def test_point_at_walks_the_route_from_the_start(m, graph):
    keys = m.tour_keys(graph)
    route = m.RouteProgress(graph, keys)
    x0, y0, _ = route.point_at(0.0)
    assert (x0, y0) == pytest.approx(m.tour_start(graph), abs=1e-3)
    xe, ye, _ = route.point_at(route.length_m)
    assert (xe, ye) == pytest.approx(m.tour_start(graph), abs=1e-3)
    x, y, heading = route.point_at(5.0)
    route.update((x, y))
    assert route.snapshot()["progress_m"] == pytest.approx(0.0, abs=1e-6)  # beyond the window
    x1, y1, _ = route.point_at(0.3)
    route.update((x1, y1))
    assert route.snapshot()["progress_m"] == pytest.approx(0.3, abs=0.005)
    assert -math.pi <= heading <= math.pi
