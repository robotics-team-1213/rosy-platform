"""All-lane coverage tour over lane_graph (mission plan stage 2). ROS-free.

`coverage_route(graph, start_xy)` returns the shortest legal chain of
directed segment keys that drives every directed segment at least once,
starting and ending at `start_xy` on the road that holds it (the parking
junction on `west` for map_v2_fleet).

The first and last keys are that road, walked partially: the tour leaves
`start_xy` along the first key and arrives at it along the last. When both
are the same direction the two partial walks together cover that key; a
key walked only partially does not count otherwise.

Legal (`is_legal`): consecutive keys share a node (a.to == b.from), a
one-way segment is never walked in reverse, and a road is never followed
straight back along itself (west:f then west:r): a U-turn is not a lane
manoeuvre on this track.

The graph is tiny (8 directed keys, out-degree 2, 1 after the no-reversal
rule at some nodes), so the search is a uniform-cost search over (node,
last key, covered set); ties break on the key sequence, so the result is
deterministic.
"""

from __future__ import annotations

import heapq

import numpy as np

#: `start_xy` must lie within this of a two-way road's centreline.
START_MAX_OFFSET_M = 0.02


def directed_keys(graph) -> list:
    """Every drivable directed key, sorted: '<name>:f', and '<name>:r'
    where the segment is two-way."""
    keys = []
    for name in sorted(graph["segments"]):
        keys.append(f"{name}:f")
        if "reverse" in graph["segments"][name]["directions"]:
            keys.append(f"{name}:r")
    return keys


def endpoints(graph, key):
    """(from_node, to_node) of a directed key."""
    name, way = key.split(":")
    seg = graph["segments"][name]
    return (seg["from"], seg["to"]) if way == "f" else (seg["to"], seg["from"])


def _points(graph, key) -> np.ndarray:
    name, way = key.split(":")
    pts = np.asarray(graph["segments"][name]["points"], float)
    return pts if way == "f" else pts[::-1]


def _arc(pts) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])


def _project(pts, xy):
    """(arc-length s, distance) of the point on polyline `pts` nearest xy."""
    p = np.asarray(xy, float)
    a, b = pts[:-1], pts[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab)
                / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0.0, 1.0)
    proj = a + ab * t[:, None]
    d = np.linalg.norm(p - proj, axis=1)
    k = int(np.argmin(d))
    return float(_arc(pts)[k] + t[k] * np.linalg.norm(ab[k])), float(d[k])


def key_length(graph, key) -> float:
    return float(_arc(_points(graph, key))[-1])


def is_legal(graph, keys) -> bool:
    """See the module docstring."""
    valid = set(directed_keys(graph))
    if not keys or any(k not in valid for k in keys):
        return False
    for a, b in zip(keys, keys[1:]):
        if endpoints(graph, a)[1] != endpoints(graph, b)[0]:
            return False
        if a.split(":")[0] == b.split(":")[0]:
            return False
    return True


def start_road(graph, start_xy) -> str:
    """The two-way road whose centreline `start_xy` lies on."""
    best = None
    for name in sorted(graph["segments"]):
        if "reverse" not in graph["segments"][name]["directions"]:
            continue
        _, d = _project(_points(graph, f"{name}:f"), start_xy)
        if best is None or d < best[0]:
            best = (d, name)
    if best is None or best[0] > START_MAX_OFFSET_M:
        raise ValueError(f"start {tuple(start_xy)} is not on a two-way road")
    return best[1]


def covered(graph, keys) -> set:
    """Directed keys a tour of `keys` (first and last partial) drives in
    full."""
    inner = set(keys[1:-1])
    if keys[0] == keys[-1]:
        inner.add(keys[0])
    return inner


def tour_length(graph, keys, start_xy) -> float:
    """Driven length of a tour: the first key from `start_xy` on, every
    inner key in full, the last key up to `start_xy`."""
    first, last = _points(graph, keys[0]), _points(graph, keys[-1])
    s_first, _ = _project(first, start_xy)
    s_last, _ = _project(last, start_xy)
    inner = sum(key_length(graph, k) for k in keys[1:-1])
    return float(_arc(first)[-1] - s_first + inner + s_last)


def coverage_route(graph, start_xy) -> list:
    """Shortest legal tour from `start_xy` back to it covering every
    directed key (see the module docstring)."""
    road = start_road(graph, start_xy)
    every = directed_keys(graph)
    bit = {k: 1 << i for i, k in enumerate(every)}
    full = (1 << len(every)) - 1
    ends = {f"{road}:f", f"{road}:r"}
    offset = {k: _project(_points(graph, k), start_xy)[0] for k in ends}
    # (cost, keys, mask of keys driven in full, terminal). Costs are rounded
    # to a micrometre so equal-length tours tie and break on `keys`.
    heap = [(round(key_length(graph, k) - offset[k], 6), (k,), 0, False) for k in sorted(ends)]
    heapq.heapify(heap)
    settled = set()
    while heap:
        cost, keys, mask, terminal = heapq.heappop(heap)
        if terminal:
            if mask == full:
                return list(keys)
            continue
        state = (keys[0], keys[-1], mask)
        if state in settled:
            continue
        settled.add(state)
        node = endpoints(graph, keys[-1])[1]
        road_here = keys[-1].split(":")[0]
        for nxt in every:
            if endpoints(graph, nxt)[0] != node or nxt.split(":")[0] == road_here:
                continue
            heapq.heappush(heap, (round(cost + key_length(graph, nxt), 6), keys + (nxt,),
                                  mask | bit[nxt], False))
            if nxt in ends:
                closing = bit[nxt] if nxt == keys[0] else 0
                heapq.heappush(heap, (round(cost + offset[nxt], 6), keys + (nxt,),
                                      mask | closing, True))
    raise ValueError("no covering tour")


def tour_start_pose(graph, keys, start_xy):
    """(x, y, yaw) at `start_xy` projected onto the first key, heading
    along it."""
    pts = _points(graph, keys[0])
    s, _ = _project(pts, start_xy)
    arc = _arc(pts)
    i = min(max(int(np.searchsorted(arc, s, side="right")) - 1, 0), len(pts) - 2)
    a, b = pts[i], pts[i + 1]
    t = 0.0 if arc[i + 1] <= arc[i] else (s - arc[i]) / (arc[i + 1] - arc[i])
    p = a + t * (b - a)
    lo, hi = pts[max(i - 1, 0)], pts[min(i + 2, len(pts) - 1)]
    return (round(float(p[0]), 4), round(float(p[1]), 4),
            round(float(np.arctan2(hi[1] - lo[1], hi[0] - lo[0])), 4))
