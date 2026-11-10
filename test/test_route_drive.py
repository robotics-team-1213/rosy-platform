"""tools/sim/route_drive.py: the stop counter and the route bodies the bench sends (D-1009)."""

import importlib.util
import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
spec = importlib.util.spec_from_file_location("route_drive", ROOT / "tools/sim/route_drive.py")
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)


def trace(*legs):
    """legs: (seconds, speed) at 10 Hz."""
    out, t = [], 0.0
    for seconds, speed in legs:
        for _ in range(int(seconds * 10)):
            out.append((t, speed))
            t += 0.1
    return out


def test_stops_are_counted_after_the_first_motion_and_a_stop_that_creeps_off_counts_once():
    # 3 s before the first motion is not a stop; 1.5 s, a 0.5 s creep and 1.0 s more are one stop; then the final stop
    samples = trace((3, 0.0), (2, 0.1), (1.5, 0.0), (0.5, 0.1), (1.0, 0.0), (2, 0.1), (2, 0.0))
    stops = rd.count_stops(samples)
    assert [round(d, 1) for _, d in stops] == [3.0, 1.9]
    assert rd.count_stops(trace((5, 0.0))) == []


def test_a_route_that_never_pauses_has_no_stop_before_its_end():
    assert rd.count_stops(trace((1, 0.0), (6, 0.1))) == []


def test_route_bodies_follow_the_east_road_and_q_is_off_the_map():
    graph = yaml.safe_load(rd.ft.GRAPH.read_text(encoding="utf-8"))
    points, end = rd.build_points(graph, "qpS", 1.0)
    assert [p["kind"] for p in points] == ["pass", "pass", "stop"]
    assert (points[0]["x"], points[0]["y"]) == rd.OFF_MAP
    assert math.isclose(end, 1.0 + 2 * rd.STEP_M)
    assert math.dist((points[1]["x"], points[1]["y"]), (points[2]["x"], points[2]["y"])) < 0.25
    assert [r.count("S") for r in rd.ROUTES.values()] == [1, 1, 2, 3]
