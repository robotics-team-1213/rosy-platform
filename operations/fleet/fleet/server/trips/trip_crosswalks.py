"""D-767 P0: where a trip route crosses each crosswalk polygon (route metres, CORE's near edge, D-491)."""

from __future__ import annotations

import bisect
import functools
import math

from fleet import site_map  # site_map._inside, looked up at call time


def crosswalk_spans(route, lo: float, hi: float, polygon, step: float = 0.02) -> list:
    """D-767 P0: ``[(near, far or None)]`` route metres in (lo, hi] where a route enters ``polygon`` from
    outside (CORE's near edge, D-491) and leaves it again: ``step`` samples, bisected to 1 mm at a crossing.
    ``route``: ``[(route m where an arc's piece starts, arc, its s there)]`` in route order (``arc.point_at``)."""
    starts = [r[0] for r in route]

    def point(d):
        base, arc, s = route[max(0, bisect.bisect_right(starts, d) - 1)]
        return arc.point_at(s + d - base)[:2]

    found, was = [], site_map._inside(point(lo), polygon)
    for k in range(max(0, math.ceil((hi - lo) / step - 1e-9))):
        a, b = lo + k * step, min(lo + (k + 1) * step, hi)
        if site_map._inside(point(b), polygon) != was:
            was = not was
            while b - a > 0.001:
                a, b = (a, (a + b) / 2) if site_map._inside(point((a + b) / 2), polygon) == was else ((a + b) / 2, b)
            found.append((b, was))
    return [(d, next((e for e, now in found[i + 1:] if not now), None)) for i, (d, now) in enumerate(found) if now]


@functools.lru_cache(maxsize=256)
def route_crosswalks(route: tuple, end: float, walks: tuple) -> tuple:
    """``((near, far or None, id), ...)`` of every crosswalk ``(id, polygon)`` along a whole route (as
    ``crosswalk_spans``, ending at ``end``). Cached: a route's geometry does not change from period to period.
    A route piece whose arc's box misses a polygon's box is never sampled (it is outside)."""
    out = []
    for walk_id, polygon in walks:
        xs, ys, windows = [p[0] for p in polygon], [p[1] for p in polygon], []
        for i, (base, arc, _s) in enumerate(route):
            stop, ax, ay = route[i + 1][0] if i + 1 < len(route) else end, *zip(*arc.polyline)
            if min(ax) <= max(xs) and max(ax) >= min(xs) and min(ay) <= max(ys) and max(ay) >= min(ys):
                if windows and windows[-1][1] == base:  # one window over touching pieces
                    windows[-1] = (windows[-1][0], stop)
                else:
                    windows.append((base, stop))
        out += [(near, far, walk_id) for lo, hi in windows for near, far in crosswalk_spans(route, lo, hi, polygon)]
    return tuple(sorted(out, key=lambda row: row[0]))
