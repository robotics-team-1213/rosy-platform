"""Subject: lane-keep bends (D-507 B9), split from lane_keep (D-362).

A bend is the lane edge turning by less than an L-corner: a corner-shaped line
(across the path ahead, near end clearly on one side, far end past the lane on
the side it leans to, no near-parallel line spanning its crossing on that side)
steeper than the keeper's steep angle but not square. B8 SIM (260919 SW bend,
~63 deg) read it at 55-66 deg: the steep rule dropped it or sided it by an
extrapolated offset that flipped, and at 66 deg the L-corner rule turned early.
Its line is the closed side's boundary; its centre line (moved a half-width
toward the robot) is pursued at the corner lookahead once it meets the robot's
path inside that radius, and straight on before ('bend_ahead'), so the robot
does not cut the inner edge. Pure functions; LaneKeeper.update owns the state
and passes its thresholds in. ROS-free, same contract onboard and in fixtures."""

from __future__ import annotations

import math

import numpy as np

from .lane_keep_junction import _across_path
from .lane_keep_pairs import _lateral_at, _pursuit_point


def nearest_first(lines):
    """Fitted lines ordered by the distance of their nearest end from base_link."""
    return sorted(lines, key=lambda l: min(float(np.linalg.norm(l["centre"] + l["direction"] * t)) for t in l["along"]))


def parallel_spans(lines, side_x, steep):
    """(lateral at side_x, near x, far x) of the fitted lines within `steep` of the heading."""
    return [(_lateral_at(l["centre"], l["direction"], side_x),
             *sorted(float(l["centre"][0] + l["direction"][0] * t) for t in l["along"]))
            for l in lines if abs(l["direction"][1]) <= math.sin(steep)]


def bend_side(ends, heading, half, parallel, limits):
    """Open side ('left'/'right') of a bend line, or None. `parallel`: (lateral at
    SIDE_X_M, near x, far x) of the frame's near-parallel lines. `limits`: the
    keeper's (steep, bend max) heading bounds; how far past the lane the far end
    must reach; the near end's offset on the closed side, at least the ambiguous
    offset and at most this fraction of the lane width (a lone boundary further is
    not ours); the margin of a parallel line spanning the crossing on the open
    side, or running past the near end on the closed side (the lane goes on
    there: a stop line, crosswalk or junction mouth, no bend)."""
    steep, most, open_m, near_min, lone_fraction, past_m = limits
    ahead = _across_path(ends, half)
    if ahead is None or not steep < abs(heading) <= most:
        return None
    near, far = sorted((float(p[0]), float(p[1])) for p in ends)
    sign = 1.0 if heading > 0.0 else -1.0
    if (sign * far[1] <= half + open_m or not near_min < -sign * near[1] <= lone_fraction * 2.0 * half
            or any((y > 0.0) == (sign > 0.0) and start <= ahead <= reach + past_m for y, start, reach in parallel)
            or any((y > 0.0) != (sign > 0.0) and reach > near[0] + past_m for y, _, reach in parallel)):
        return None
    return "left" if sign > 0.0 else "right"


def as_transverse(bends, transverse_min):
    """Bend lines past the transverse angle as junction-rule transverse entries: a bend
    and a junction mouth look alike in one frame, and junctions fail closed."""
    return [(r["centre"], r["direction"], r["ends_m"], False) for r in bends
            if abs(math.radians(r["heading_deg"])) > transverse_min]


def bend_target(bends, half, radius, target, strategy):
    """(target, strategy, room) with `room` how far ahead a target may lie (inf:
    unbounded). On the nearest bend's centre line at `radius`; while that line
    meets the robot's path beyond `radius`, the lane's own target held short of
    the bend line (its crossing less a half-width: 'bend_ahead'), or (None,
    None, inf) -- HOLD -- without a lane-side boundary or room. `bends`: records
    with centre, direction, ends_m and open side."""
    best = None
    for record in bends:
        centre, direction = record["centre"], record["direction"]
        normal = np.array([-direction[1], direction[0]])
        if float(np.dot(normal, centre)) > 0.0:
            normal = -normal
        origin = centre + normal * half
        along = direction if (direction[1] > 0.0) == (record["open"] == "left") else -direction
        meet = float(origin[0] - origin[1] * along[0] / along[1])
        if best is None or meet < best[0]:
            best = (meet, origin, along, record["open"], _across_path(record["ends_m"], half))
    meet, origin, along, side, cross = best
    if meet > radius:
        room = None if cross is None else cross - half
        if target is None or room is None or room <= 0.0:
            return None, None, math.inf
        return stop_short(target, room), "bend_ahead", room
    return _pursuit_point(origin, along, radius)[0], f"bend_{side}", math.inf


def near_run(points, ends, half, parallel, limits):
    """[line] for a rejected steep line: the straight paint run nearest base_link on its near end's side
    (the lane edge before it curves into it; m20 roundabout exit), or [] if that side has a `parallel` line
    a half-width long. `limits`: the keeper's (steep angle, ambiguous offset, inlier half-band, gap, shortest
    piece). Paint past the ambiguous offset, inside the lane width and a half-width of the near end; nearest
    first, a point joins within the half-band of the run's own y-on-x fit, a gap ends the run."""
    steep, ambiguous, band, gap, shortest = limits
    near_y = float(min(ends, key=lambda p: float(p[0]))[1])
    if any((y > 0.0) == (near_y > 0.0) and far - near >= half for y, near, far in parallel): return []  # noqa: E701
    lateral = points[:, 1] * math.copysign(1.0, near_y)
    pool = points[(lateral > ambiguous) & (lateral <= 2.0 * half) & (np.abs(points[:, 1] - near_y) <= half)]
    n = sx = sy = sxx = sxy = 0.0
    first = last = None
    fit = lambda: (n * sxy - sx * sy) / (n * sxx - sx * sx)  # noqa: E731 — slope of y on x
    for x, y in pool[np.argsort(pool[:, 0], kind="stable")].tolist():
        if last is not None and x - last > gap:
            break
        if last is not None and last - first >= band and abs(y - (sy + fit() * (n * x - sx)) / n) > band:
            continue
        first, last = x if first is None else first, x
        n, sx, sy, sxx, sxy = n + 1, sx + x, sy + y, sxx + x * x, sxy + x * y
    if last is None or last - first < band or abs(math.atan(fit())) > steep or (last - first) * math.hypot(1.0, fit()) < shortest:
        return []
    direction = np.array([1.0, fit()]) / math.hypot(1.0, fit())
    return [{"centre": np.array([first, (sy + fit() * (n * first - sx)) / n]), "direction": direction,
             "along": (0.0, (last - first) / float(direction[0]))}]


def stop_short(target, room):
    """`target` pulled back along its ray to no further than `room` ahead."""
    target = np.asarray(target, float)
    return target * min(1.0, room / float(target[0])) if target[0] > room else target


def runs_past(boundaries, open_left, ahead, margin):
    """True when a boundary on the open side runs on past a corner line `ahead`
    (less `margin`): the lane goes on there, so that line is no L-corner."""
    for record in boundaries:
        if (record["side"] == "left") != open_left:
            continue
        far = max(float(p[0]) for p in record["ends_m"])
        if far >= ahead - margin:
            return True
    return False
