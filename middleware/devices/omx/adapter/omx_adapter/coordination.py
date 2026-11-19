"""Two arms on fixed paths: which segment may start when, so they stay apart and finish soonest.

The coordination diagram (O'Donnell & Lozano-Perez 1989). Paths stay as planned, because D-911 evidence binds to the exact
path; only the timing is chosen. A node (i, j) means arm a finished i segments and arm b j. An edge moves one arm, or both,
and exists only when everything it sweeps keeps `margin_m` apart. Dijkstra over these edges gives the shortest schedule.

Execution is gated on measured progress, never on the clock (D-780 barriers are that gate): an arm that lags or stops stays
inside what its segment swept, which the schedule already cleared against everything the peer may do meanwhile.
"""
from __future__ import annotations

import heapq
import math
from typing import NamedTuple


class Segment(NamedTuple):
    name: str
    duration_s: float
    poses: list  # each pose is a list of capsules (a, b, radius), all in one common frame


def line_distance(p1, q1, p2, q2) -> float:
    """Closest distance between segments p1-q1 and p2-q2 (Ericson, Real-Time Collision Detection 5.1.9)."""
    d1x, d1y, d1z = q1[0] - p1[0], q1[1] - p1[1], q1[2] - p1[2]
    d2x, d2y, d2z = q2[0] - p2[0], q2[1] - p2[1], q2[2] - p2[2]
    rx, ry, rz = p1[0] - p2[0], p1[1] - p2[1], p1[2] - p2[2]
    a = d1x * d1x + d1y * d1y + d1z * d1z
    e = d2x * d2x + d2y * d2y + d2z * d2z
    f = d2x * rx + d2y * ry + d2z * rz
    if a <= 1e-12 and e <= 1e-12:
        s = t = 0.0
    elif a <= 1e-12:
        s, t = 0.0, f / e
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
    else:
        c = d1x * rx + d1y * ry + d1z * rz
        if e <= 1e-12:
            s, t = -c / a, 0.0
        else:
            b = d1x * d2x + d1y * d2y + d1z * d2z
            denom = a * e - b * b
            s = (b * f - c * e) / denom if denom > 1e-12 else 0.0
            if s < 0.0:
                s = 0.0
            elif s > 1.0:
                s = 1.0
            t = (b * s + f) / e
            if t < 0.0:
                s, t = -c / a, 0.0
            elif t > 1.0:
                s, t = (b - c) / a, 1.0
        if s < 0.0:
            s = 0.0
        elif s > 1.0:
            s = 1.0
    gx = p1[0] + d1x * s - p2[0] - d2x * t
    gy = p1[1] + d1y * s - p2[1] - d2y * t
    gz = p1[2] + d1z * s - p2[2] - d2z * t
    return math.hypot(gx, gy, gz)


def clearance(poses_a, poses_b) -> float:
    """Smallest surface distance between any capsule of any pose in `poses_a` and any in `poses_b`."""
    return min(line_distance(a1, a2, b1, b2) - ra - rb
               for pose_a in poses_a for a1, a2, ra in pose_a
               for pose_b in poses_b for b1, b2, rb in pose_b)


def _clearance_at_least(poses_a, poses_b, margin_m) -> bool:
    for pose_a in poses_a:
        for a1, a2, ra in pose_a:
            for pose_b in poses_b:
                for b1, b2, rb in pose_b:
                    if line_distance(a1, a2, b1, b2) - ra - rb < margin_m:
                        return False
    return True


def plan(a: list, b: list, margin_m: float, start=(0, 0)):
    """{"steps": [{"a": i or None, "b": j or None}, ...], "makespan_s"} from `start`, or None when no order keeps them apart."""
    n, m = len(a), len(b)
    rest_a = [s.poses[:1] for s in a] + [a[-1].poses[-1:]]
    rest_b = [s.poses[:1] for s in b] + [b[-1].poses[-1:]]
    memo = {}

    def free(key, poses_a, poses_b):
        if key not in memo:
            memo[key] = _clearance_at_least(poses_a, poses_b, margin_m)
        return memo[key]

    def edges(i, j):
        if not free(("rest", i, j), rest_a[i], rest_b[j]):
            return
        if i < n and j < m and free(("both", i, j), a[i].poses, b[j].poses):
            yield (i + 1, j + 1), max(a[i].duration_s, b[j].duration_s), {"a": i, "b": j}
        if i < n and free(("a", i, j), a[i].poses, rest_b[j]):
            yield (i + 1, j), a[i].duration_s, {"a": i, "b": None}
        if j < m and free(("b", i, j), rest_a[i], b[j].poses):
            yield (i, j + 1), b[j].duration_s, {"a": None, "b": j}

    best, came, heap = {start: 0.0}, {}, [(0.0, start)]
    while heap:
        cost, node = heapq.heappop(heap)
        if cost > best[node]:
            continue
        if node == (n, m):
            if not free(("rest", n, m), rest_a[n], rest_b[m]):
                return None
            steps = []
            while node != start:
                node, step = came[node]
                steps.append(step)
            return {"steps": steps[::-1], "makespan_s": round(cost, 3)}
        for to, duration, step in edges(*node):
            if cost + duration < best.get(to, math.inf):
                best[to], came[to] = cost + duration, (node, step)
                heapq.heappush(heap, (cost + duration, to))
    return None


def ready(steps: list, arm: str, segment: int, done_a: int, done_b: int) -> bool:
    """May `arm` start its `segment` now? Everything the schedule put before that segment's step must have finished."""
    needed = {"a": 0, "b": 0}
    for step in steps:
        if step[arm] == segment:
            return done_a >= needed["a"] and done_b >= needed["b"]
        for key in needed:
            if step[key] is not None:
                needed[key] = step[key] + 1
    return False


def rigid_between(points_from: list, points_to: list) -> tuple:
    """(yaw, tx, ty) that best maps 2D `points_from` onto `points_to` (least squares, no scale)."""
    count = len(points_from)
    if count < 2 or count != len(points_to):
        raise ValueError("rigid_between needs at least two matched points")
    fx, fy = (sum(p[k] for p in points_from) / count for k in (0, 1))
    tx, ty = (sum(p[k] for p in points_to) / count for k in (0, 1))
    cross = sum((p[0] - fx) * (q[1] - ty) - (p[1] - fy) * (q[0] - tx) for p, q in zip(points_from, points_to))
    inner = sum((p[0] - fx) * (q[0] - tx) + (p[1] - fy) * (q[1] - ty) for p, q in zip(points_from, points_to))
    yaw = math.atan2(cross, inner)
    c, s = math.cos(yaw), math.sin(yaw)
    return yaw, tx - (c * fx - s * fy), ty - (s * fx + c * fy)


def moved(capsules: list, rigid: tuple) -> list:
    yaw, tx, ty = rigid
    c, s = math.cos(yaw), math.sin(yaw)
    point = lambda p: (c * p[0] - s * p[1] + tx, s * p[0] + c * p[1] + ty, p[2])  # noqa: E731
    return [(point(p), point(q), r) for p, q, r in capsules]


def thinned(poses: list, step_m: float) -> list:
    """Keeps a pose whenever a capsule end moved `step_m`, and grows every radius by step_m / 2: what happens between two
    kept poses stays inside the grown capsules, so sparse samples cannot hide a pass."""
    kept, last = [], None
    for index, pose in enumerate(poses):
        if last is None or index == len(poses) - 1 or any(
                math.dist(u, v) >= step_m for c, d in zip(pose, last) for u, v in zip(c[:2], d[:2])):
            kept.append([(p, q, r + step_m / 2) for p, q, r in pose])
            last = pose
    return kept


def rendezvous(a: list, b: list, margin_m: float, max_meets: int = 4):
    """The same problem for D-780 barriers, which release only when both arms have arrived. Between two meets each arm runs on
    its own, so every pair in that block must keep the margin. {"meets": [(i, j), ...], "makespan_s"}, or None."""
    n, m = len(a), len(b)
    rest_a = [s.poses[:1] for s in a] + [a[-1].poses[-1:]]
    rest_b = [s.poses[:1] for s in b] + [b[-1].poses[-1:]]
    memo = {}
    cum_a, cum_b = [0.0], [0.0]
    for segment in a:
        cum_a.append(cum_a[-1] + segment.duration_s)
    for segment in b:
        cum_b.append(cum_b[-1] + segment.duration_s)

    def pair(x, y):  # x: a's segment index or ("rest", i); y likewise
        if (x, y) not in memo:
            poses_a = rest_a[x[1]] if isinstance(x, tuple) else a[x].poses
            poses_b = rest_b[y[1]] if isinstance(y, tuple) else b[y].poses
            memo[x, y] = _clearance_at_least(poses_a, poses_b, margin_m)
        return memo[x, y]

    def block_free(i, j, i2, j2):
        xs = list(range(i, i2)) or [("rest", i)]
        ys = list(range(j, j2)) or [("rest", j)]
        return all(pair(x, y) for x in xs for y in ys)

    start, goal = (0, 0, 0), (n, m)
    best, came, heap = {start: 0.0}, {}, [(0.0, start)]
    while heap:
        cost, node = heapq.heappop(heap)
        if cost > best[node]:
            continue
        i, j, used = node
        if (i, j) == goal:
            meets = []
            while node != start:
                node = came[node]
                meets.append(node[:2])
            return {"meets": [m_ for m_ in meets[::-1] if m_ != (0, 0)], "makespan_s": round(cost, 3)}
        for i2 in range(i, n + 1):
            for j2 in range(j, m + 1):
                if (i2, j2) == (i, j) or ((i2, j2) != goal and used >= max_meets) or not block_free(i, j, i2, j2):
                    continue
                to = (i2, j2, used + ((i2, j2) != goal))
                total = cost + max(cum_a[i2] - cum_a[i], cum_b[j2] - cum_b[j])
                if total < best.get(to, math.inf):
                    best[to], came[to] = total, node
                    heapq.heappush(heap, (total, to))
    return None
