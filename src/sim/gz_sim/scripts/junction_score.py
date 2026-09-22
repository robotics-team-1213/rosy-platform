#!/usr/bin/env python3
"""Junction scenarios from lane_graph.yaml and trajectory scoring. ROS-free.

A directed segment is '<name>:f' (from -> to) or '<name>:r' (reverse, only
for two-way roads). A scenario is one transition through a node: arrive on
`into`, leave on `out`, never straight back along the same road. The robot
starts START_BEFORE_M before the node on `into`'s centreline, heading along
it; the scenario ends END_AFTER_M into `out`.

Scoring is direction-aware (spec §4.4 review, 2026-09-23): distance-to-line
membership alone cannot tell a real transit from a pivot U-turn back along
`into`, around the far node, and backwards along `out` -- for a pair like
into=ring_e:f/out=east:f (or west/ring_w), both segments join the SAME two
nodes, so a reversed trajectory never strays onto an "other" segment and
still passes near `end_point` (order is never checked). `score()` guards
against this two ways: an arc-length coordinate along into+out must stay
near-monotonic, and each step's motion direction must not point more than
90 degrees away from the local forward tangent, outside a junction node's
ambiguous radius.
"""

import json
import math
from pathlib import Path

import numpy as np
import yaml

START_BEFORE_M = 0.35
END_AFTER_M = 0.30
#: A trajectory point belongs to the segment whose centreline is nearest.
PASS_MAX_CENTRE_DEV_M = 0.040
#: Within this radius of a junction node every segment's centreline
#: converges, so nearest-line membership cannot tell into/out from a wrong
#: branch there, nor tell forward from reversed motion.
NODE_AMBIGUOUS_M = 0.12
#: Backward travel in the into+out arc-length coordinate beyond this much
#: (a bit more than the ~0.01 m point spacing) marks the trajectory as
#: going the wrong way, not just noisy.
BACKWARD_S_TOLERANCE_M = 0.02
#: Motion direction is only checked between samples at least this far
#: apart; closer than that, heading is noise-dominated.
MOTION_MIN_STEP_M = 0.005
#: How far (in arc length) around the previous point's position the next
#: point's nearest-on-path search looks. into+out pairs that join the same
#: two nodes by different routes make the combined path a closed loop whose
#: start and end coincide in space; an unrestricted global search there is
#: ambiguous (see _nearest_on_path). 0.5 m comfortably covers any real
#: per-sample travel (recorded odom or the ~0.01 m graph-point spacing
#: used to build test trajectories) while still excluding the loop's other
#: end.
SEARCH_WINDOW_M = 0.5
#: Ring annulus (roundabout radius 0.2514 m) that ring_ccw_ok watches.
RING_R_MIN_M, RING_R_MAX_M = 0.20, 0.30
#: Angular jitter tolerance for the ring's net-CCW check.
RING_CCW_TOLERANCE_RAD = 0.02


def directed(graph):
    out = []
    for name in sorted(graph["segments"]):
        seg = graph["segments"][name]
        out.append((f"{name}:f", seg["from"], seg["to"]))
        if "reverse" in seg["directions"]:
            out.append((f"{name}:r", seg["to"], seg["from"]))
    return out


def directed_points(graph, key):
    name, way = key.split(":")
    pts = np.array(graph["segments"][name]["points"], float)
    return pts if way == "f" else pts[::-1]


def _arc_length(pts):
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])


def distance_to(pts, point):
    p = np.asarray(point, float)
    a, b = pts[:-1], pts[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12),
                0.0, 1.0)
    return float(np.min(np.linalg.norm(p - (a + ab * t[:, None]), axis=1)))


def _nearest_on_path(path, arc_s, point, s_window=None):
    """(arc-length s, segment index) of the point on `path` nearest `point`.

    `into`+`out` pairs that join the same two nodes by different routes
    (east/ring_e, west/ring_w) make `path` a closed loop: its start and end
    coincide in space. A plain global nearest search is then ambiguous right
    at that shared point -- it can snap to s=0 instead of s=len(path),
    reporting a huge, spurious jump backward. `s_window`, an (lo, hi) arc-
    length range seeded from the previous point's s, keeps the search local
    to where the trajectory actually is instead of the whole path; pass
    None only for the very first point, where there is no "previous"."""
    p = np.asarray(point, float)
    a, b = path[:-1], path[1:]
    idx = np.arange(len(a))
    if s_window is not None:
        lo, hi = s_window
        mask = (arc_s[:-1] >= lo) & (arc_s[:-1] <= hi)
        if mask.any():
            a, b, idx = a[mask], b[mask], idx[mask]
    ab = b - a
    ab_len2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12)
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / ab_len2, 0.0, 1.0)
    proj = a + ab * t[:, None]
    d2 = np.einsum("ij,ij->i", p - proj, p - proj)
    k = int(np.argmin(d2))
    i = int(idx[k])
    seg_len = float(np.linalg.norm(ab[k]))
    return float(arc_s[i] + t[k] * seg_len), i


def _ring_ccw_ok(graph, trajectory):
    """False if any contiguous stretch of `trajectory` inside the ring
    annulus (RING_R_MIN_M..RING_R_MAX_M about the roundabout centre) has
    net clockwise angular travel -- the ring is one-way CCW."""
    centre = np.array(graph["roundabout"]["centre"], float)
    pts = np.asarray(trajectory, float)
    if len(pts) < 2:
        return True
    r = np.linalg.norm(pts - centre, axis=1)
    in_ring = (r >= RING_R_MIN_M) & (r <= RING_R_MAX_M)
    angles = np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0])
    i, n = 0, len(pts)
    while i < n:
        if not in_ring[i]:
            i += 1
            continue
        j = i
        while j < n and in_ring[j]:
            j += 1
        if j - i >= 2:
            stretch = np.unwrap(angles[i:j])
            if stretch[-1] - stretch[0] < -RING_CCW_TOLERANCE_RAD:
                return False
        i = j
    return True


def scenarios(graph):
    segs = directed(graph)
    result = []
    for node in sorted(graph["nodes"]):
        arriving = [(k, a) for k, a, b in segs if b == node]
        leaving = [(k, b) for k, a, b in segs if a == node]
        for into, _ in arriving:
            for out, _ in leaving:
                if into.split(":")[0] == out.split(":")[0]:
                    continue          # straight back along the same road
                pts = directed_points(graph, into)
                s = _arc_length(pts)
                i = int(np.searchsorted(s, s[-1] - START_BEFORE_M))
                i = min(max(i, 1), len(pts) - 2)
                heading = math.atan2(*(pts[i + 1] - pts[i - 1])[::-1])
                result.append({"node": node, "into": into, "out": out,
                               "start": (round(float(pts[i][0]), 4), round(float(pts[i][1]), 4),
                                         round(heading, 4))})
    return result


def score(graph, scenario, trajectory):
    into = directed_points(graph, scenario["into"])
    out = directed_points(graph, scenario["out"])
    into_road = scenario["into"].split(":")[0]
    out_road = scenario["out"].split(":")[0]
    others = [directed_points(graph, k) for k, _, _ in directed(graph)
              if k.split(":")[0] not in (into_road, out_road)]
    node = np.array(graph["nodes"][scenario["node"]], float)
    # Every graph node the into+out path touches is ambiguous, not just the
    # scenario's own: a ring segment's START_BEFORE_M start sits only ~0.02 m
    # from its OTHER (upstream) node, where other segments meet too.
    junction_nodes = [node, np.asarray(into[0], float), np.asarray(out[-1], float)]
    out_s = _arc_length(out)
    end_point = out[int(np.searchsorted(out_s, END_AFTER_M))]

    combined = np.vstack([into, out[1:]])
    combined_s = _arc_length(combined)
    seg_vec = combined[1:] - combined[:-1]
    seg_len = np.linalg.norm(seg_vec, axis=1)
    seg_unit = np.divide(seg_vec, seg_len[:, None], out=np.zeros_like(seg_vec),
                         where=seg_len[:, None] > 0)

    pts = np.asarray(trajectory, float)
    max_dev, wrong, reached, wrong_way = 0.0, False, False, False
    prev_s, prev_p = None, None
    for p in pts:
        near_node = any(math.dist(p, jn) <= NODE_AMBIGUOUS_M for jn in junction_nodes)
        d_into, d_out = distance_to(into, p), distance_to(out, p)
        d_best = min(d_into, d_out)
        if not near_node:
            d_other = min((distance_to(o, p) for o in others), default=math.inf)
            if d_other + 1e-6 < d_best:
                wrong = True
            max_dev = max(max_dev, d_best)
        if math.dist(p, end_point) < 0.05:
            reached = True

        s_window = None if prev_s is None else (prev_s - SEARCH_WINDOW_M, prev_s + SEARCH_WINDOW_M)
        s_here, seg_i = _nearest_on_path(combined, combined_s, p, s_window)
        if prev_s is not None and (prev_s - s_here) > BACKWARD_S_TOLERANCE_M:
            wrong_way = True
        if prev_p is not None and not near_node:
            step = p - prev_p
            step_len = float(np.linalg.norm(step))
            if step_len >= MOTION_MIN_STEP_M:
                if float(np.dot(step / step_len, seg_unit[seg_i])) < 0.0:
                    wrong_way = True
        prev_s, prev_p = s_here, p

    ring_ccw_ok = _ring_ccw_ok(graph, pts)
    branch_ok = reached and not wrong and not wrong_way
    return {"branch_ok": branch_ok, "reached_end": reached,
            "max_centre_dev_m": round(max_dev, 4),
            "wrong_way": wrong_way, "ring_ccw_ok": ring_ccw_ok,
            "pass": branch_ok and ring_ccw_ok and max_dev <= PASS_MAX_CENTRE_DEV_M}


def rescore(graph, results_json_path, track_dir):
    """Re-score already-recorded track.json files against the current
    scoring rules, without re-running Gazebo. Matches junction_harness.py's
    per-scenario folder naming: "<k:02d>_<node>_<into>_to_<out>" with the
    ':' stripped. Missing track.json files score against just the start
    pose (same fallback junction_harness.py itself uses when a track is
    empty), so an old, incomplete evidence set still re-scores instead of
    raising."""
    results_json_path = Path(results_json_path)
    track_dir = Path(track_dir)
    old = json.loads(results_json_path.read_text(encoding="utf-8"))
    rescored = []
    for idx, entry in enumerate(old):
        scenario = {k: entry[k] for k in ("node", "into", "out", "start")}
        folder = f"{idx:02d}_{scenario['node']}_{scenario['into']}_to_{scenario['out']}".replace(":", "")
        track_path = track_dir / folder / "track.json"
        if track_path.is_file():
            track = json.loads(track_path.read_text(encoding="utf-8"))
        else:
            track = []
        merged = dict(entry)
        merged.update(score(graph, scenario, track or [scenario["start"][:2]]))
        rescored.append(merged)
    return rescored


def _rescore_cli(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="Re-score already-recorded track.json files without re-running Gazebo.")
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True,
                        help="results.json written by junction_harness.py")
    parser.add_argument("--tracks", type=Path, required=True,
                        help="directory holding the per-scenario track.json folders "
                             "(usually the --out of junction_harness.py)")
    parser.add_argument("--write", type=Path, default=None,
                        help="output path (default: <results>_rescored.json next to --results)")
    args = parser.parse_args(argv)
    graph = yaml.safe_load(args.graph.read_text(encoding="utf-8"))
    rescored = rescore(graph, args.results, args.tracks)
    out = args.write or args.results.with_name(args.results.stem + "_rescored.json")
    out.write_text(json.dumps(rescored, indent=2))
    passed = sum(r["pass"] for r in rescored)
    print(f"{passed}/{len(rescored)} passed (rescored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_rescore_cli())
