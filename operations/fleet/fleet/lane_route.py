"""Ordered lane-graph edges become one polyline and one short next point.

A console point goal stays ``{x, y, yaw}``. This module does not call CORE.
The far junction is not a goal: Nav2 would cut across the empty floor.
``STEP_M`` is the existing 0.20 m traffic sample. On the 0.2514 m ring that
straight step sags about 0.02 m, inside the lane and inside the body clearance.
A longer bend whose 0.20 m chord would put the body outside the imported lane
uses a shorter step, still past the device goal ball. The device goal ball has
to be shorter than that step, or the follower is already inside it and only
rotates.

A closed lap starts and ends on the same point. ``along_m`` keeps the
along-track progress so that shared point is the end once the route has
been followed, and the start on a fresh route.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core_common.robot_body import NOMINAL_BODY
from fleet.site_map import IMPORT_WIDTH_M

STEP_M = 0.20
#: Shorter than ``STEP_M`` when a bend's chord would leave the painted lane, and
#: still longer than the device goal ball (0.10 m).
MIN_STEP_M = 0.12
OFF_M = 0.08
DONE_M = 0.05
MAX_EDGES = 8
#: Half the imported lane, minus the nominal body. The centre may sit this far off the paint.
BODY_CLEAR_M = IMPORT_WIDTH_M / 2.0 - NOMINAL_BODY.half_width_m
_SAMPLE_M = 0.02
#: Two projections of one pose (a closed junction) agree within a millimetre.
_TIE_M = 1e-3


class LaneRouteError(ValueError):
    """``str(self)`` is the API code."""


@dataclass(frozen=True)
class LaneStep:
    x: float
    y: float
    yaw: float
    s_m: float
    remaining_m: float
    #: Along-track pose used to choose this step. The caller keeps it.
    at_m: float = 0.0


def route_lines(edge_ids: list[str] | tuple[str, ...], painted):
    """Stored polylines in order from the active site map's ``Painted`` (D-488).

    Unknown or broken joins raise ``LaneRouteError``.
    """
    if not edge_ids:
        raise LaneRouteError("ROUTE_EMPTY")
    if len(edge_ids) > MAX_EDGES:
        raise LaneRouteError("ROUTE_TOO_LONG")
    lines = []
    previous: str | None = None
    for edge_id in edge_ids:
        try:
            line = painted.line(edge_id)
        except KeyError as exc:
            raise LaneRouteError("ROUTE_UNKNOWN_EDGE") from exc
        if previous is not None and previous != line.start:
            raise LaneRouteError("ROUTE_DISCONTINUOUS")
        lines.append(line)
        previous = line.end
    return tuple(lines)


def _located(lines, x: float, y: float, along_m: float) -> tuple[float, float]:
    """``(at_m, total_m)`` of the pose on ``lines``.

    The closest projection wins. A closed junction is two projections of one
    pose; ``along_m`` picks the one the route has already reached.
    """
    if not math.isfinite(along_m) or along_m < 0.0:
        raise ValueError("along_m must be a nonnegative finite distance")
    best: float | None = None
    found: list[tuple[float, float]] = []
    cursor = 0.0
    for line in lines:
        dist, s_m, _tangent = line.project(x, y)
        found.append((dist, cursor + s_m))
        if best is None or dist < best:
            best = dist
        cursor += line.length_m
    if best is None or best > OFF_M:
        raise LaneRouteError("ROUTE_OFF_LANE")
    tied = [item for item in found if item[0] <= best + _TIE_M]
    _dist, at_m = min(tied, key=lambda item: (abs(item[1] - along_m), -item[1]))
    return at_m, cursor


def _point(lines, s_global: float) -> tuple[float, float]:
    walked = 0.0
    for line in lines:
        end = walked + line.length_m
        if s_global <= end + 1e-12 or line is lines[-1]:
            x, y, _yaw = line.point_at(s_global - walked)
            return x, y
        walked = end
    raise LaneRouteError("ROUTE_OFF_LANE")


def chord_off_m(lines, s0: float, s1: float) -> float:
    """How far the polyline sits off the straight chord from ``s0`` to ``s1``."""
    if s1 < s0:
        s0, s1 = s1, s0
    ax, ay = _point(lines, s0)
    bx, by = _point(lines, s1)
    span2 = (bx - ax) ** 2 + (by - ay) ** 2
    worst = 0.0
    s = s0
    while True:
        px, py = _point(lines, s)
        if span2 <= 1e-18:
            off = math.hypot(px - ax, py - ay)
        else:
            t = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / span2
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
            off = math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay)))
        if off > worst:
            worst = off
        if s >= s1 - 1e-12:
            return worst
        s = s1 if s + _SAMPLE_M >= s1 else s + _SAMPLE_M


def _ahead(lines, s_global: float, total: float) -> float:
    """Along-track target. The full step stands unless its chord leaves the lane."""
    reach = min(STEP_M, total - s_global)
    if reach <= MIN_STEP_M or chord_off_m(lines, s_global, s_global + reach) <= BODY_CLEAR_M:
        return s_global + reach
    lo, hi = MIN_STEP_M, reach
    for _ in range(16):
        mid = (lo + hi) / 2.0
        if chord_off_m(lines, s_global, s_global + mid) <= BODY_CLEAR_M:
            lo = mid
        else:
            hi = mid
    return s_global + lo


def step_facts(lines, step: LaneStep | None) -> dict:
    """What this short step holds. A finished route says it is complete."""
    if step is None:
        return {"complete": True, "step_m": 0.0, "chord_m": 0.0, "body_clear_m": BODY_CLEAR_M,
                "body_inside": True, "s_m": None}
    chord = chord_off_m(lines, step.at_m, step.s_m)
    return {"complete": False, "step_m": step.s_m - step.at_m, "chord_m": chord,
            "body_clear_m": BODY_CLEAR_M, "body_inside": chord <= BODY_CLEAR_M + 1e-9,
            "s_m": step.s_m}


def next_step(lines, x: float, y: float, *, along_m: float = 0.0) -> LaneStep | None:
    """The next point on ``lines``, or None at the end.

    The step is ``STEP_M`` when that chord keeps the nominal body inside the
    imported lane, and shorter (still at least ``MIN_STEP_M``) when it would
    not. A remainder of ``MIN_STEP_M`` or less keeps the end. A pose more than
    ``OFF_M`` off the polyline raises ``ROUTE_OFF_LANE``. ``along_m`` is how
    far along this route the pose has already been. Zero is a fresh route.
    """
    s_global, total = _located(lines, x, y, along_m)
    if total - s_global <= DONE_M:
        return None
    target = _ahead(lines, s_global, total)
    walked = 0.0
    for line in lines:
        end = walked + line.length_m
        if target <= end or line is lines[-1]:
            px, py, yaw = line.point_at(target - walked)
            return LaneStep(px, py, yaw, target, total - target, s_global)
        walked = end
    raise LaneRouteError("ROUTE_OFF_LANE")
