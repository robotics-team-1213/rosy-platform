"""D-941 3: the speed table v(s) along one planned route.

Pure: built from the site map and a trip plan's segments ``(edge_id, forward, s_from, s_to)``.
Each point's limit is the smallest of the lane's ``speed_cap_mps``, a measured curve cap for the
local turn radius, and the stripe cap near a ``stop`` or ``slow`` place; then the braking limit is applied
backwards so the robot is already slow when a curve or stripe starts, and the route ends at 0.
Not sent to a robot yet (D-941 opens: one robot's table is checked first).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

STEP_M = 0.01
DECEL_MPS2 = 0.3       # shortcut: nominal; replace with the measured body stop distance (D-941 2)
ACCEL_MPS2 = 0.3
STRIPE_HALF_M = 0.06   # a stripe slows this far either side of its stop place
STRIPE_MPS = 0.05
CHANGE_MPS = 0.002     # rows are kept only where the limit changes this much


@dataclass(frozen=True)
class CurveCap:
    """Measured: at a turn radius up to ``radius_m`` the robot keeps the lane at ``mps``."""
    radius_m: float
    mps: float


def speed_table(site_map, segments: Sequence[tuple[str, bool, float, float]], *,
                curve_caps: Sequence[CurveCap] = (), start_mps: float = 0.0, closed: bool = False) -> dict:
    """``closed``: the segments form a loop, so nothing stops at the end and braking wraps around."""
    edges = {e.id: e for e in site_map.edges}
    stops = [(p.id, p.x, p.y) for p in site_map.places if p.kind in ("stop", "slow")]   # slow: stripe, no stop
    caps = sorted(curve_caps, key=lambda c: c.radius_m)
    points: list[tuple[float, float, float, Optional[float]]] = []   # x, y, lane cap, turn radius
    for edge_id, forward, s_from, s_to in segments:
        edge = edges[edge_id]
        line = list(edge.polyline if forward else reversed(edge.polyline))
        for x, y, radius in _walk(line, s_from, s_to):
            points.append((x, y, edge.speed_cap_mps, radius))
    if not points:
        return {"length_m": 0.0, "rows": [], "stripes": [], "curve_caps_measured": bool(caps)}
    s = [0.0]
    for a, b in zip(points, points[1:]):
        s.append(s[-1] + math.dist(a[:2], b[:2]))
    limit = [_cap(lane, radius, caps) for _, _, lane, radius in points]
    stripes = []
    for stop_id, sx, sy in stops:
        near = min(range(len(points)), key=lambda i: math.dist(points[i][:2], (sx, sy)))
        if math.dist(points[near][:2], (sx, sy)) > STEP_M * 3:
            continue   # the route does not cross this stripe
        stripes.append({"place": stop_id, "s_m": round(s[near], 3)})
        for i in range(len(points)):
            d = abs(s[i] - s[near])
            if (min(d, s[-1] - d) if closed else d) <= STRIPE_HALF_M + 1e-9:
                limit[i] = min(limit[i], STRIPE_MPS)
    n = len(limit)
    if not closed:
        limit[-1] = 0.0
    for k in range(2 * n - 2 if closed else n - 1, 0, -1):    # brake before what comes next; twice round a loop
        i, j = (k - 1) % n, k % n
        limit[i] = min(limit[i], math.sqrt(limit[j] ** 2 + 2 * DECEL_MPS2 * max(0.0, s[j] - s[i])))
    v = list(limit) if closed else [min(limit[0], start_mps)] + limit[1:]
    for k in range(1, 2 * n if closed else n):     # cannot be faster than the start allows
        i, j = (k - 1) % n, k % n
        v[j] = min(v[j], math.sqrt(v[i] ** 2 + 2 * ACCEL_MPS2 * max(0.0, s[j] - s[i])))
    rows = [(0.0, v[0])]
    for i in range(1, len(v)):
        if abs(v[i] - rows[-1][1]) >= CHANGE_MPS or i == len(v) - 1:
            rows.append((s[i], v[i]))
    return {"length_m": round(s[-1], 3), "rows": [[round(a, 3), round(b, 3)] for a, b in rows],
            "stripes": sorted(stripes, key=lambda r: r["s_m"]), "curve_caps_measured": bool(caps)}


def _cap(lane: float, radius: Optional[float], caps: Sequence[CurveCap]) -> float:
    if radius is None:
        return lane
    return min(lane, next((c.mps for c in caps if radius <= c.radius_m), lane))   # tightest bucket


def _walk(line, s_from: float, s_to: float):
    """Points every STEP_M from s_from to s_to on the polyline, each with its local turn radius."""
    radii = [None] + [_radius(a, b, c) for a, b, c in zip(line, line[1:], line[2:])] + [None]
    lengths = [math.dist(a, b) for a, b in zip(line, line[1:])]
    total = sum(lengths)
    s_to = min(s_to, total)
    n = max(1, round((s_to - s_from) / STEP_M))
    for k in range(n + 1):
        target = s_from + (s_to - s_from) * k / n
        acc = 0.0
        for j, seg in enumerate(lengths):
            if acc + seg >= target or j == len(lengths) - 1:
                t = 0.0 if seg == 0 else min(1.0, max(0.0, (target - acc) / seg))
                (ax, ay), (bx, by) = line[j], line[j + 1]
                ends = [r for r in (radii[j], radii[j + 1]) if r is not None]
                yield ax + t * (bx - ax), ay + t * (by - ay), min(ends) if ends else None
                break
            acc += seg


def _radius(a, b, c) -> Optional[float]:
    """Circumradius through three points; None on a straight run."""
    ab, bc, ca = math.dist(a, b), math.dist(b, c), math.dist(c, a)
    cross = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    return None if cross < 1e-9 else ab * bc * ca / (2 * cross)
