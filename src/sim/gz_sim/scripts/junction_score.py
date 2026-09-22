#!/usr/bin/env python3
"""Junction scenarios from lane_graph.yaml and trajectory scoring. ROS-free.

A directed segment is '<name>:f' (from -> to) or '<name>:r' (reverse, only
for two-way roads). A scenario is one transition through a node: arrive on
`into`, leave on `out`, never straight back along the same road. The robot
starts START_BEFORE_M before the node on `into`'s centreline, heading along
it; the scenario ends END_AFTER_M into `out`.
"""

import math

import numpy as np

START_BEFORE_M = 0.35
END_AFTER_M = 0.30
#: A trajectory point belongs to the segment whose centreline is nearest.
PASS_MAX_CENTRE_DEV_M = 0.040
#: Within this radius of the node every segment's centreline converges, so
#: nearest-line membership cannot tell into/out from a wrong branch there.
NODE_AMBIGUOUS_M = 0.12


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
    out_s = _arc_length(out)
    end_point = out[int(np.searchsorted(out_s, END_AFTER_M))]
    max_dev, wrong, reached = 0.0, False, False
    for p in np.asarray(trajectory, float):
        near_node = math.dist(p, node) <= NODE_AMBIGUOUS_M
        d_into, d_out = distance_to(into, p), distance_to(out, p)
        d_best = min(d_into, d_out)
        if not near_node:
            d_other = min((distance_to(o, p) for o in others), default=math.inf)
            if d_other + 1e-6 < d_best:
                wrong = True
            max_dev = max(max_dev, d_best)
        if math.dist(p, end_point) < 0.05:
            reached = True
    return {"branch_ok": reached and not wrong, "reached_end": reached,
            "max_centre_dev_m": round(max_dev, 4),
            "pass": reached and not wrong and max_dev <= PASS_MAX_CENTRE_DEV_M}
